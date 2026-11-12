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
MAX_ELEMENTS = 4000
_NAME_RE = re.compile(r"^[^\W\d_][\w'’.\-]*(?: [^\W\d_][\w'’.\-]*){0,3}$")


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
        self._said: Dict[str, List[str]] = {}  # the lines read, by speaker
        self._known: set = set()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._described = False
        self._lock = threading.Lock()

    def start(self, started_at: float, known_names: Optional[List[str]] = None) -> None:
        self.stop()
        with self._lock:
            self.started_at = started_at or time.time()
            self.marks, self.names, self.lines = [], [], 0
            self._said, self._known = {}, {n.lower() for n in (known_names or []) if n}
            self.state, self.error = "idle", ""
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="teams_captions")
        self._thread.start()

    def stop(self) -> Dict[str, Any]:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._thread = None
        return self.snapshot()

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            counts: Dict[str, int] = {}
            for m in self.marks:
                counts[m["name"]] = counts.get(m["name"], 0) + 1
            return {"state": self.state, "error": self.error, "lines": self.lines,
                    "names": list(self.names), "counts": counts, "marks": list(self.marks)}

    # ---- reading
    def _take(self, found: List[Tuple[str, str]]) -> None:
        now = time.time()
        with self._lock:
            for name, line in found:
                said = self._said.setdefault(name.lower(), [])
                low = line.lower()
                # the line still being said grows at its end, and the older lines stay on screen
                same = next((i for i, s in enumerate(said) if s == low or low.startswith(s) or s.startswith(low)), None)
                if same is not None:
                    if len(low) > len(said[same]):
                        said[same] = low
                    continue
                said.append(low)
                self.lines += 1
                if name not in self.names:
                    self.names.append(name)
                self.marks.append({"at": round(max(0.0, now - self.started_at - CAPTION_LAG_SEC), 2),
                                   "name": name, "text": line[:200]})

    def _run(self) -> None:
        if sys.platform != "win32":
            self._set("unavailable", "только в Windows")
            return
        try:
            import clr  # pythonnet: the Windows component screen readers use

            clr.AddReference("UIAutomationClient")
            clr.AddReference("UIAutomationTypes")
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

        while not self._stop.is_set():
            try:
                wins = [w for w in AutomationElement.RootElement.FindAll(TreeScope.Children, Condition.TrueCondition)
                        if process_name(w.Current.ProcessId) in TEAMS_PROCESSES]
                if not wins:
                    self._set("no_window")
                else:
                    texts, panel_found = [], False
                    for w in wins:
                        for panel in self._panels(w, Condition, TreeScope):
                            panel_found = True
                            items = []
                            for el in panel.FindAll(TreeScope.Descendants, Condition.TrueCondition):
                                try:
                                    c = el.Current
                                    if c.ControlType == ControlType.Text and c.Name.strip():
                                        items.append(c.Name.strip())
                                except Exception:
                                    continue
                            if not self._described:
                                self._describe(panel, items)
                            texts.extend(items)
                    if panel_found:
                        self._take(pairs(texts, self._known))
                        self._set("reading")
                    else:
                        self._set("no_captions")
            except Exception as e:
                traceback.print_exc()
                self._set("error", str(e)[:200])
            self._stop.wait(POLL_SEC)

    def _panels(self, window, Condition, TreeScope) -> List[Any]:
        found, walked = [], 0
        for el in window.FindAll(TreeScope.Descendants, Condition.TrueCondition):
            walked += 1
            if walked > MAX_ELEMENTS:
                break
            try:
                c = el.Current
                label = f"{c.Name} {c.AutomationId}".lower()
            except Exception:
                continue
            if any(w in label for w in CAPTION_WORDS):
                found.append(el)
        # the innermost panel holds the lines; an outer one (the window's region) holds them too
        return found[-1:] if found else []

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


def enabled() -> bool:
    from app.database import get_all_settings

    return (get_all_settings().get("teams_captions") or "false").lower() == "true"
