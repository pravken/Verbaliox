"""
Who is speaking, read from the live captions of Microsoft Teams while a recording runs (optional,
setting teams_captions; docs/teams-captions.md).

Teams writes a name above every caption line. Read through Windows accessibility (UI Automation, as
Windows Narrator reads a window: nothing is pressed, nothing is sent anywhere), each new line gives a
«speaking now» mark — {at: seconds into the recording, name} — and the names join the studio's
participants. After transcription the voice heard at a person's marks gets their name
(transcriber.apply_speaker_marks).

The layout of the Teams window is not documented and changes between versions: the panel is found by
its name ("caption" / "субтитр"), and its text elements are read in order as name / line pairs. The
first time a panel is found its structure goes to the log, so a version that reads differently can be
fixed from it. Windows only; elsewhere (and without pythonnet) the reader says it is not available.
"""

import os
import re
import sys
import threading
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

TEAMS = "teams"  # the transcript version made of the captions (the chip «Субтитры Teams»)
POLL_SEC = 1.0
CAPTION_LAG_SEC = 1.5          # a line shows up about this long after it was said
TEAMS_PROCESSES = {"ms-teams", "teams", "msteams"}
CAPTION_WORDS = ("caption", "субтитр")
RECENT_LINES = 40              # a reading is compared with this many latest lines of its speaker only
MAX_ELEMENTS = 25000            # elements of a window looked at when the panel is searched for
FIND_EVERY_SEC = 5.0           # how often the panel is searched for again while it is not found
NOT_A_PANEL = {"Button", "MenuItem", "CheckBox", "Hyperlink", "SplitButton", "RadioButton", "ToolTip", "Image"}
_NAME_RE = re.compile(r"^[^\W\d_][\w'’.\-]*(?: [^\W\d_][\w'’.\-]*){0,3}$")


UIA_ASSEMBLIES = ("UIAutomationTypes", "UIAutomationClient")
_UIA_STRONG = ", Version=4.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35"


def uia_paths(name: str) -> List[str]:
    """Where Windows keeps the UI Automation assembly of .NET Framework 4 (it ships with every Windows
    10/11): the global assembly cache, then the WPF folder of the framework."""
    import os

    win = os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows"
    net = os.path.join(win, "Microsoft.NET")
    return [os.path.join(net, "assembly", "GAC_MSIL", name, "v4.0_4.0.0.0__31bf3856ad364e35", f"{name}.dll"),
            os.path.join(net, "Framework64", "v4.0.30319", "WPF", f"{name}.dll"),
            os.path.join(net, "Framework", "v4.0.30319", "WPF", f"{name}.dll")]


def load_uia() -> None:
    """Loads UI Automation through pythonnet. Its version 3 does not find an assembly of the global
    cache by its short name («Could not load file or assembly 'UIAutomationClient'»): the full name is
    tried next, then the file itself. Raises when none of them loads."""
    import os

    import clr

    for name in UIA_ASSEMBLIES:
        errors = []
        for ref in (name, name + _UIA_STRONG, *[p for p in uia_paths(name) if os.path.isfile(p)]):
            try:
                clr.AddReference(ref)
                break
            except Exception as e:
                errors.append(f"{ref}: {e}".splitlines()[0][:160])
        else:
            raise RuntimeError(f"{name} не загружен: " + " | ".join(errors))


def looks_like_name(text: str, known: Optional[set] = None) -> bool:
    """A caption author: one of the known names, or 1–4 capitalised words without sentence punctuation."""
    t = " ".join(str(text or "").split())
    if not t or len(t) > 48:
        return False
    if known and t.lower() in known:
        return True
    if t[-1] in ".?!…,:;" or not _NAME_RE.match(t):
        return False
    return all(w[:1].isupper() for w in t.split())


def pairs(texts: List[str], known: Optional[set] = None) -> List[Tuple[str, str]]:
    """The text elements of the caption panel, in order, as (name, line): a name, then the lines under
    it until the next name (Teams repeats the name above each line, or groups lines under one)."""
    out: List[Tuple[str, str]] = []
    name = ""
    for raw in texts:
        t = " ".join(str(raw or "").split())
        if not t:
            continue
        if looks_like_name(t, known):
            name = t
            continue
        if name:
            out.append((name, t))
    return out


def same_line(a: str, b: str) -> bool:
    """Two readings of one caption line (lowered): it grew at its end, or Teams corrected its words as
    it went («…связи азии запишите…» → «…связи, запишите…»): one starts or ends the same way as the
    other, or most of it is the same."""
    import difflib

    if a == b:
        return True
    short, long_ = sorted((len(a), len(b)))
    # a reading that grew: only a real start of the line counts («да» begins every «да, …» said before)
    if (a.startswith(b) or b.startswith(a)) and (short >= 12 or short >= 0.5 * long_):
        return True
    if short < 12:
        return False
    head = len(os.path.commonprefix([a, b]))
    tail = len(os.path.commonprefix([a[::-1], b[::-1]]))
    if head >= max(12, short * 0.5) or tail >= max(15, short * 0.5):
        return True
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() >= 0.75


def choose_panel(candidates: List[Tuple[str, List[str]]], known: Optional[set] = None) -> Optional[int]:
    """Which of the elements named like captions (its ControlType, its text elements) holds the lines:
    the one whose texts make the most name / line pairs, of those the smallest (the innermost), never
    a button such as «Caption settings». None when none of them holds a caption line."""
    holding = [i for i, (kind, texts) in enumerate(candidates) if kind not in NOT_A_PANEL and pairs(texts, known)]

    def inside(inner: List[str], outer: List[str]) -> bool:
        n = len(inner)
        return n < len(outer) and any(outer[k:k + n] == inner for k in range(len(outer) - n + 1))

    # an outer region (the call's stage, the whole window) holds the panel's lines and more: left out
    inner = [i for i in holding
             if not any(j != i and inside(candidates[j][1], candidates[i][1]) for j in holding)]
    if not inner:
        return None
    return max(inner, key=lambda i: (len(pairs(candidates[i][1], known)), -len(candidates[i][1])))


def as_transcript(marks: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The caption lines read during a recording as a transcript version of their own: each line a
    phrase of its speaker (named as in Teams), its words spread over the time until the next line.
    None when no line was read."""
    from datetime import datetime

    lines = sorted((m for m in marks or [] if (m.get("text") or "").strip()), key=lambda m: float(m.get("at") or 0))
    if not lines:
        return None
    try:
        from app.diarizer import SPEAKER_COLORS
    except Exception:
        SPEAKER_COLORS = ["#0A84FF"]
    ids: Dict[str, str] = {}
    speakers: Dict[str, Dict[str, Any]] = {}
    segments: List[Dict[str, Any]] = []
    for i, m in enumerate(lines):
        name = str(m.get("name") or "").strip() or "Teams"
        if name not in ids:
            sid = f"SPEAKER_{len(ids):02d}"
            ids[name] = sid
            speakers[sid] = {"id": sid, "name": name, "color": SPEAKER_COLORS[(len(ids) - 1) % len(SPEAKER_COLORS)]}
        text = " ".join(str(m["text"]).split())
        words = text.split()
        start = float(m.get("at") or 0)
        nxt = float(lines[i + 1].get("at") or 0) if i + 1 < len(lines) else start + 0.4 * len(words)
        end = max(start + 0.5, min(nxt, start + max(1.5, 0.45 * len(words))))
        step = (end - start) / max(1, len(words))
        segments.append({"id": i, "start": round(start, 2), "end": round(end, 2), "speaker": ids[name], "text": text,
                         "words": [{"word": " " + w, "start": round(start + k * step, 2), "end": round(start + (k + 1) * step, 2),
                                    "prob": 1.0} for k, w in enumerate(words)]})
    return {"segments": segments, "speakers": speakers, "language": "",
            "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


class Reader:
    def __init__(self) -> None:
        self.started_at = 0.0
        self.marks: List[Dict[str, Any]] = []
        self.names: List[str] = []
        self.lines = 0
        self.state = "idle"          # idle | reading | no_window | no_captions | unavailable | error
        self.error = ""
        self._said: Dict[str, List[List[Any]]] = {}  # the lines read, by speaker
        self._live: Optional[Tuple[str, List[Any]]] = None  # (speaker, entry) of the line being said
        self._known: set = set()
        self._stop = threading.Event()  # replaced at each start: a reader thread late to stop keeps its own
        self._seeded = False            # the lines on screen before the recording began are known, not marked
        self._thread: Optional[threading.Thread] = None
        self._described = False
        self._panel: Any = None
        self._found_at = 0.0
        self._last_logged = ""
        self._lock = threading.Lock()

    def start(self, started_at: float, known_names: Optional[List[str]] = None) -> None:
        self.stop()
        with self._lock:
            self.started_at = started_at or time.time()
            self.marks, self.names, self.lines = [], [], 0
            self._said, self._known = {}, {n.lower() for n in (known_names or []) if n}
            self._live, self._seeded = None, False
            self.state, self.error = "idle", ""
            self._panel, self._found_at = None, 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(self._stop,), daemon=True, name="teams_captions")
        self._thread.start()

    def stop(self) -> Dict[str, Any]:
        """Ends the reading; returns what this recording read, and forgets it: a next recording
        that does not read the captions must not get these lines."""
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._thread = None
        snap = self.snapshot()
        with self._lock:
            self.marks, self.names, self.lines, self._said, self._live = [], [], 0, {}, None
            self.state = "idle"
        return snap

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            marks = [dict(m) for m in self.marks if not m.get("merged")]
            counts: Dict[str, int] = {}
            for m in marks:
                counts[m["name"]] = counts.get(m["name"], 0) + 1
            return {"state": self.state, "error": self.error, "lines": self.lines,
                    "names": list(self.names), "counts": counts, "marks": marks}

    # ---- reading
    def _take(self, found: List[Tuple[str, str]]) -> None:
        """The pairs on screen now, in order. The last one is the line still being said: Teams rewrites
        it until the next line comes («1345» → «123456» → «13456789 10»), so each reading of it replaces
        its text; the lines above it are said, each kept once in its latest wording."""
        now = time.time()
        with self._lock:
            if not self._seeded and found:
                # The panel as it was when the recording began: those lines were said before it, they
                # are known (not marked at 0 s, where they named the first voice heard); the last one may
                # be the line being said now and is taken as usual
                self._seeded = True
                for name, line in found[:-1]:
                    self._said.setdefault(name.lower(), []).append([line.lower(), None])
                found = found[-1:]
            closed = False  # the line being said before is now above the last one: it is finished
            for k, (name, line) in enumerate(found):
                said = self._said.setdefault(name.lower(), [])  # [line lowered, index of its mark or None]
                if len(said) > RECENT_LINES * 2:  # only the latest lines can still be on screen
                    del said[:-RECENT_LINES]
                low = line.lower()
                live = self._live
                if k == len(found) - 1 and live is not None and not closed and live[0] == name.lower() \
                        and live[1] in said and not any(e is not live[1] and same_line(e[0], low) for e in said[-RECENT_LINES:]):
                    self._set_text(live[1], low, line)  # the same line, still being said
                    continue
                matches = [e for e in said[-RECENT_LINES:] if same_line(e[0], low)]
                if matches:
                    same = matches[0]  # the earliest: the line began then
                    for extra in matches[1:]:  # pieces of the same line read apart before: one line now
                        said.remove(extra)
                        if extra[1] is not None:
                            self.marks[extra[1]]["merged"] = True
                            self.lines -= 1
                    if low != same[0] and (len(matches) > 1 or len(low) >= len(same[0]) * 0.8):
                        self._set_text(same, low, line)
                    if live is not None and same is live[1] and k < len(found) - 1:
                        closed = True
                    if k == len(found) - 1:
                        self._live = (name.lower(), same)
                    continue
                entry = [low, len(self.marks)]
                said.append(entry)
                self.lines += 1
                if name not in self.names:
                    self.names.append(name)
                self.marks.append({"at": round(max(0.0, now - self.started_at - CAPTION_LAG_SEC), 2),
                                   "name": name, "text": line[:200]})
                if k == len(found) - 1:
                    self._live = (name.lower(), entry)

    def _set_text(self, entry: List[Any], low: str, line: str) -> None:
        entry[0] = low
        if entry[1] is not None:  # a line from before the recording has no mark
            self.marks[entry[1]]["text"] = line[:200]

    def _run(self, stop: threading.Event) -> None:
        if sys.platform != "win32":
            self._set("unavailable", "только в Windows")
            return
        try:
            load_uia()  # the Windows component screen readers use
            from System.Diagnostics import Process
            from System.Windows.Automation import AutomationElement, Condition, ControlType, TreeScope
        except Exception as e:
            self._set("unavailable", f"нет доступа к окнам Windows: {e}"[:200])
            return

        def process_name(pid: int) -> str:
            try:
                return Process.GetProcessById(pid).ProcessName.lower()
            except Exception:
                return ""

        api = (AutomationElement, Condition, ControlType, TreeScope)
        while not stop.is_set():
            try:
                texts = self._read_panel(api) if self._panel is not None else None
                if texts is None:  # not found yet, or Teams changed its window: searched again
                    self._panel = None
                    if time.time() - self._found_at >= FIND_EVERY_SEC:
                        self._found_at = time.time()
                        wins = [w for w in AutomationElement.RootElement.FindAll(TreeScope.Children, Condition.TrueCondition)
                                if process_name(w.Current.ProcessId) in TEAMS_PROCESSES]
                        if not wins:
                            self._set("no_window")
                        else:
                            found = self._find_panel(wins, api, self._known)
                            if found is None:
                                self._set("no_captions", f"окон Teams: {len(wins)}")
                            else:
                                self._panel, texts = found
                if texts is not None:
                    self._take(pairs(texts, self._known))
                    self._set("reading")
            except Exception as e:
                traceback.print_exc()
                self._panel = None
                self._set("error", str(e)[:200])
            stop.wait(POLL_SEC)

    @staticmethod
    def _texts(el, api) -> List[str]:
        AutomationElement, Condition, ControlType, TreeScope = api
        out = []
        for t in el.FindAll(TreeScope.Descendants, Condition.TrueCondition):
            try:
                c = t.Current
                if c.ControlType == ControlType.Text and c.Name.strip():
                    out.append(c.Name.strip())
            except Exception:
                continue
        return out

    def _read_panel(self, api) -> Optional[List[str]]:
        """The text of the panel found earlier, or None when it is gone (closed, the window changed)."""
        try:
            _ = self._panel.Current.Name  # raises once the element is no longer in the window
            return self._texts(self._panel, api)
        except Exception:
            return None

    def _find_panel(self, windows, api, known) -> Optional[Tuple[Any, List[str]]]:
        """(the caption panel, its text elements) in the Teams windows, or None. Every element whose name
        or id speaks of captions is a candidate; the one holding name / line pairs wins (choose_panel)."""
        AutomationElement, Condition, ControlType, TreeScope = api
        candidates: List[Tuple[Any, str, List[str]]] = []
        for w in windows:
            walked = 0
            for el in w.FindAll(TreeScope.Descendants, Condition.TrueCondition):
                walked += 1
                if walked > MAX_ELEMENTS or len(candidates) >= 12:
                    break
                try:
                    c = el.Current
                    label = f"{c.Name} {c.AutomationId}".lower()
                    kind = c.ControlType.ProgrammaticName.replace("ControlType.", "")
                except Exception:
                    continue
                if any(word in label for word in CAPTION_WORDS) and kind not in NOT_A_PANEL:
                    candidates.append((el, kind, self._texts(el, api)))
        i = choose_panel([(k, t) for _, k, t in candidates], known)
        if i is None:
            self._log_once("[teams] no captions panel; candidates: "
                           + ("; ".join(f"{k} {self._label(el)} texts={len(t)}" for el, k, t in candidates[:8]) or "none"))
            return None
        el, _, texts = candidates[i]
        if not self._described:
            self._describe(el, texts)
        return el, texts

    @staticmethod
    def _label(el) -> str:
        try:
            c = el.Current
            return f"name={c.Name[:60]!r} id={c.AutomationId[:60]!r}"
        except Exception:
            return "?"

    def _log_once(self, text: str) -> None:
        if self._last_logged != text:
            self._last_logged = text
            print(text[:1500], flush=True)

    def _describe(self, panel, items: List[str]) -> None:
        self._described = True
        try:
            c = panel.Current
            print(f"[teams] captions panel: {c.ControlType.ProgrammaticName} name={c.Name!r} id={c.AutomationId!r} "
                  f"class={c.ClassName!r}; first text elements: {items[:8]!r}", flush=True)
        except Exception:
            pass

    def _set(self, state: str, error: str = "") -> None:
        with self._lock:
            self.state, self.error = state, error


_reader = Reader()


def start(started_at: float, known_names: Optional[List[str]] = None) -> None:
    _reader.start(started_at, known_names)


def stop() -> Dict[str, Any]:
    return _reader.stop()


def status() -> Dict[str, Any]:
    return _reader.snapshot()


def check(timeout: float = 25.0) -> Dict[str, Any]:
    """«Проверить» in the settings: what the reader sees in Teams right now, without a recording —
    the Teams windows, whether the caption panel is found, and the last lines in it."""
    if _reader._thread and _reader._thread.is_alive():  # a recording reads them now: what it read last
        st = _reader.snapshot()
        marks = st.pop("marks", None) or []
        return {**st, "windows": None, "sample": [{"name": m["name"], "text": m.get("text", "")[:120]} for m in marks[-3:]]}
    out: Dict[str, Any] = {"state": "error", "error": "", "windows": 0, "sample": []}

    def run() -> None:
        if sys.platform != "win32":
            out.update(state="unavailable", error="только в Windows")
            return
        try:
            load_uia()
            from System.Diagnostics import Process
            from System.Windows.Automation import AutomationElement, Condition, ControlType, TreeScope
        except Exception as e:
            out.update(state="unavailable", error=f"нет доступа к окнам Windows: {e}"[:200])
            return

        def process_name(pid: int) -> str:
            try:
                return Process.GetProcessById(pid).ProcessName.lower()
            except Exception:
                return ""
        try:
            wins = [w for w in AutomationElement.RootElement.FindAll(TreeScope.Children, Condition.TrueCondition)
                    if process_name(w.Current.ProcessId) in TEAMS_PROCESSES]
            out["windows"] = len(wins)
            if not wins:
                out["state"] = "no_window"
                return
            found = Reader()._find_panel(wins, (AutomationElement, Condition, ControlType, TreeScope), set())
            if found is None:
                out["state"] = "no_captions"
                return
            out["state"] = "reading"
            out["sample"] = [{"name": n, "text": t[:120]} for n, t in pairs(found[1])[-3:]]
        except Exception as e:
            traceback.print_exc()
            out.update(state="error", error=str(e)[:200])

    th = threading.Thread(target=run, daemon=True, name="teams_check")
    th.start()
    th.join(timeout)
    if th.is_alive():
        out.update(state="error", error="Teams не ответил вовремя")
    print(f"[teams] check: {out['state']} windows={out['windows']} lines={len(out['sample'])} {out['error']}", flush=True)
    return out


def enabled() -> bool:
    from app.database import get_all_settings

    return (get_all_settings().get("teams_captions") or "false").lower() == "true"
