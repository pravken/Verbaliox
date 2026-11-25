"""
Live captions while recording, optionally translated.

The page sends the recording's audio as 16 kHz mono 16-bit PCM about every 0.25 s. The server
keeps the audio that is not yet final and, at most every LIVE_STEP_SEC, transcribes that window
(at most LIVE_WINDOW_SEC) with the Whisper model already in memory. Phrases that end well before
the end of the window are final: they are kept, their audio is dropped and, if asked, they are
translated by Ollama in the background. The rest of the window is shown as a draft line.

Russian speech with GigaAM goes by VAD phrases instead (app/live_phrases.py): only the phrase being spoken is
recognized, by the GigaAM v3 e2e-CTC int8, and it is final once after a pause. English and the other languages
keep the window for the final lines (Parakeet: the phrases without context lose 6–9 points of WER,
bench-report/asr-2026-11.md); between the window's runs the VAD follows the speech too and only the phrase being
spoken is recognized for the draft line, every 0.3 s or more (live_phrases.SpeechFollow, DraftPace). The window and
these drafts share one budget of the caption copy's time (CAPTION_BUSY_SHARE).

After recording stops the usual full transcription of the saved file runs; live captions are only
for following along, so they favour speed (greedy decoding, short window) over accuracy.
"""

import json
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from app.database import get_all_settings
from app.paths import APP_DIR

_clock = time.perf_counter  # times a run of the window (_window_ran)
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0

SR = 16000
# transcribe the window at most this often: every 2 s, as when the page sent the audio once a second (the window ran
# on every second piece; its final lines and its load were measured so, bench-report/asr-2026-11-check.md)
LIVE_STEP_SEC = 2.0
PHRASE_STEP_SEC = 0.2     # by VAD phrases: every piece of audio the page sends (about every 0.25 s)
LIVE_WINDOW_SEC = 20.0    # longest audio kept undecided (forced to final beyond it)
FINAL_MARGIN_SEC = 1.6    # a phrase ending this long before the window end is final
# The window and the drafts of the phrase being spoken between its runs take together at most this share of the time of
# the caption copy (its WINDOW_THREADS threads): with the drafts at a third of it on their own besides the window,
# English captions took up to 63 % of a 4-thread copy. The drafts get what the window leaves (live_phrases.DraftPace,
# share), at least MIN_DRAFT_SHARE. They run on the same copy as the window: a copy of their own on 2 threads would hold
# Parakeet fp32 twice (3 GB more), and ONNX Runtime fixes the threads of a session when it is made.
CAPTION_BUSY_SHARE = 0.35
MIN_DRAFT_SHARE = 0.05
# The drafts go off when a run of the window takes over DRAFTS_OFF_SEC (the window keeps the draft line alone) and on
# again only under DRAFTS_ON_SEC: a run near the limit turned them off and on at every run. The VAD listens either way.
DRAFTS_OFF_SEC = 0.6
DRAFTS_ON_SEC = 0.4
SESSION_IDLE_SEC = 120.0  # sessions without audio for this long are dropped
# Final lines a session keeps (the page has its own copy of all of them): the question about the meeting so far
# (/api/live/{id}/ask) takes the latest part of them, and translations reach only the recent ones
LINES_KEPT = 3000
RECENT_LINES = 200  # the lines whose translation or target language the answers still follow

WORKER_IDLE_SEC = 120.0   # the caption worker is closed (VRAM freed) after this long unused
WORKER_START_SEC = 900.0  # the worker loads (and on first use downloads) its model before it answers
WORKER_ANSWER_SEC = 60.0  # a window not answered in this time: the worker hangs and is replaced
WORKER_RETRY_SEC = (5.0, 15.0, 30.0, 60.0)  # waits before starting a worker again after failures

_sessions: Dict[str, "LiveSession"] = {}
BAD_WINDOWS_RESTART = 3  # caption windows in a row the worker failed before it is started again
_sessions_lock = threading.Lock()


class _Seg:
    __slots__ = ("start", "end", "text")

    def __init__(self, start: float, end: float, text: str):
        self.start, self.end, self.text = start, end, text


class _CaptionWorker:
    """
    The Whisper model for captions runs in app/live_worker.py: if it fails natively (CUDA out of
    memory can abort a process) only captions stop, never the app or the recording.
    """

    def __init__(self) -> None:
        self.proc: Optional[subprocess.Popen] = None
        self.lock = threading.Lock()
        self.last_used = 0.0
        self.stderr_tail: List[str] = []
        self.model_name = ""
        self._out: "queue.Queue[bytes]" = queue.Queue()
        # A worker that cannot start (no model, no memory, broken CUDA) is not started again on every
        # window of audio: after each failure the next try waits longer (WORKER_RETRY_SEC)
        self.failures = 0
        self.retry_at = 0.0
        self.bad_windows = 0  # windows in a row the worker answered with an error
        self.last_error = ""
        threading.Thread(target=self._reaper, daemon=True, name="live_worker_reaper").start()

    def _start(self) -> None:
        if time.time() < self.retry_at:
            raise RuntimeError(self.last_error or "процесс распознавания не запустился")
        cmd = [sys.executable, "-m", "app.live_worker"]
        try:
            from app.shutdown import track

            self.proc = track(subprocess.Popen(
                cmd, cwd=str(APP_DIR), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=_NO_WINDOW, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            ))
            self._out = queue.Queue()
            threading.Thread(target=self._drain, args=(self.proc,), daemon=True).start()
            threading.Thread(target=self._read, args=(self.proc, self._out), daemon=True).start()
            line = self._readline(WORKER_START_SEC)
            if not line:
                raise RuntimeError("процесс распознавания не запустился: " + " | ".join(self.stderr_tail[-3:]))
            self.model_name = json.loads(line).get("model") or ""
        except Exception as e:
            self._kill()
            self.last_error = str(e)[:300]
            self.retry_at = time.time() + WORKER_RETRY_SEC[min(self.failures, len(WORKER_RETRY_SEC) - 1)]
            self.failures += 1
            raise
        self.failures = 0
        self.retry_at = 0.0

    @staticmethod
    def _read(proc, out: "queue.Queue[bytes]") -> None:
        for line in proc.stdout:
            out.put(line)
        out.put(b"")  # the process ended

    def _readline(self, timeout: float) -> bytes:
        try:
            return self._out.get(timeout=timeout)
        except queue.Empty:
            raise RuntimeError("процесс распознавания не отвечает")

    def _drain(self, proc) -> None:
        for raw in proc.stderr:
            text = raw.decode("utf-8", "replace").rstrip()
            self.stderr_tail = (self.stderr_tail + [text])[-20:]

    def transcribe(self, audio: np.ndarray, lang: Optional[str]) -> Tuple[List[_Seg], Optional[str], float]:
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()
        with self.lock:
            for attempt in range(2):
                try:
                    if self.proc is None or self.proc.poll() is not None:
                        self._start()
                    from app import vocab

                    head = {"lang": lang, "bytes": len(pcm), "hotwords": vocab.hotwords()}
                    self.proc.stdin.write((json.dumps(head, ensure_ascii=False) + "\n").encode())
                    self.proc.stdin.write(pcm)
                    self.proc.stdin.flush()
                    line = self._readline(WORKER_ANSWER_SEC)
                    if not line:
                        raise RuntimeError("процесс распознавания завершился")
                    res = json.loads(line)
                    self.last_used = time.time()
                    if not res.get("ok"):
                        # One bad window: the worker is fine (live_worker.py answers and goes on), the
                        # window is skipped. Several in a row: something broke, it is started again
                        self.bad_windows += 1
                        if self.bad_windows < BAD_WINDOWS_RESTART:
                            return [], None, 0.0
                        self.bad_windows = 0
                        raise RuntimeError(res.get("error") or "ошибка распознавания")
                    self.bad_windows = 0
                    segs = [_Seg(float(a), float(b), str(t)) for a, b, t in res["segments"]]
                    return segs, res.get("language"), float(res.get("prob") or 0.0)
                except (OSError, ValueError, RuntimeError) as e:
                    self._kill()
                    if attempt or time.time() < self.retry_at:
                        raise RuntimeError(f"Субтитры остановлены: {e}") from e
        return [], None, 0.0

    def preload(self) -> None:
        with self.lock:
            if self.proc is None or self.proc.poll() is not None:
                try:
                    self._start()
                    self.last_used = time.time()
                except Exception:
                    traceback.print_exc()
                    self._kill()

    def _kill(self) -> None:
        if self.proc is not None:
            try:
                self.proc.kill()
            except OSError:
                pass
            self.proc = None

    def _reaper(self) -> None:
        while True:
            time.sleep(15)
            active = has_sessions()
            if self.proc is not None and not active and time.time() - self.last_used > WORKER_IDLE_SEC:
                with self.lock:
                    self._kill()


_worker: Optional[_CaptionWorker] = None
_worker_lock = threading.Lock()


def _caption_worker() -> _CaptionWorker:
    global _worker
    with _worker_lock:
        if _worker is None:
            _worker = _CaptionWorker()
        return _worker


def _translate_choice(settings: Dict[str, Any], speed: str) -> str:
    """The translation model saved for «Качество» or «Скорость»; "" is «Авто» (app/live_translate.choose_models)."""
    from app.live_translate import CHOICE_KEYS

    return str(settings.get(CHOICE_KEYS.get(speed, CHOICE_KEYS["quality"])) or "").strip()


class LiveSession:
    def __init__(self, lang: Optional[str], translate_to: Optional[str], capture_id: Optional[str] = None,
                 speed: str = "quality", pair: Optional[List[str]] = None):
        self.id = uuid.uuid4().hex
        self.capture_id = capture_id
        # The language chosen for speech (None: detected in every window, so a meeting may switch
        # between languages); self.lang is the language heard last, for translation and the UI
        self.speech_lang = lang if lang and lang != "auto" else None
        self.lang = self.speech_lang
        settings = get_all_settings()
        self.caption_choice = settings.get("live_whisper_model") or "auto"
        self.onnx_model = caption_onnx_model(settings, self.speech_lang)
        self.draft = False  # the page shows the draft line: translate it too
        # «Качество» or «Скорость»: the translation model is the one saved for it (Settings → «Модели перевода»,
        # or chosen in the studio, which saves it there too); "" is «Авто»
        self.speed = speed if speed in ("quality", "fast") else "quality"
        self.translate_choice = _translate_choice(settings, self.speed)
        self.translate_to = translate_to or None
        self.pair = list(pair or ["ru", "en"])[:2]  # the two languages of translate_to="auto"
        self._buf = np.zeros(0, dtype=np.float32)  # self.audio is its start (room for the next pieces after it)
        self._n = 0
        self.offset = 0.0           # recording time (s) of self.audio[0]
        self.base = 0               # the same in samples (exact: the VAD phrases count in samples)
        self._ph = None             # app/live_phrases.PhraseState while captions go by VAD phrases
        self._follow = None         # app/live_phrases.SpeechFollow: drafts of the phrase in the window scheme (False: off)
        self._win_draft: List[Tuple[int, int, str]] = []  # the window's draft sentences at its last run (samples)
        self._window_cost = 0.0     # seconds the last run of the window took
        self._drafts_on = True      # the drafts of the phrase in the window scheme (off while the window is slow)
        self.last_window_at = 0.0   # self.received when the window was last transcribed
        self.received = 0.0         # seconds of audio received in total
        self.last_run_at = 0.0      # self.received when the last step ran
        self.lines: List[Dict[str, Any]] = []
        # What the answers have reported: the version grows with each change of a line (new, translated, its target
        # language set), and the page sends the version it has, so an answer carries only what changed since
        self._version = 0
        self._seen: Dict[int, Tuple[Any, Any]] = {}  # line id -> (translation, target) as last reported
        self._changed: Dict[int, int] = {}            # line id -> the version of its last change
        self._state_lock = threading.Lock()
        self.partial = ""
        self.error = ""
        self.touched = time.time()
        self._busy = threading.Lock()
        # the audio buffer is grown by the request thread and cut by the step thread at once: without a
        # lock a cut could be undone by an append made from the buffer before it (the phrase came twice)
        self._audio_lock = threading.Lock()
        self.translator = None
        if translate_to:
            from app.live_translate import LiveTranslator

            # Starts loading the translation model now, while the first phrase is being spoken
            self.translator = LiveTranslator(lambda: self.lang, translate_to, speed, self.pair)
        self._next_id = 1

    # -------------------------------------------------------------- audio in
    @property
    def audio(self) -> np.ndarray:
        """The audio kept (not final yet), from self.offset: a view of the buffer, valid while this step holds it
        (the pieces received meanwhile go after its end, a cut only moves the start)."""
        return self._buf[:self._n]

    @audio.setter
    def audio(self, value: np.ndarray) -> None:
        self._buf = np.asarray(value, dtype=np.float32)
        self._n = self._buf.size

    def _append(self, chunk: np.ndarray) -> None:
        """A piece after the audio kept (call with _audio_lock held): into the room after it, so a piece every 0.25 s
        does not copy the whole window each time; the buffer grows by doubling."""
        need = self._n + chunk.size
        if need > self._buf.size:
            grown = np.empty(max(need, 2 * self._n, 4 * SR), dtype=np.float32)
            grown[:self._n] = self._buf[:self._n]
            self._buf = grown
        self._buf[self._n:need] = chunk
        self._n = need

    def add_pcm16(self, data: bytes) -> None:
        if len(data) % 2:
            data = data[:-1]
        chunk = np.frombuffer(data, dtype="<i2").astype(np.float32)
        chunk *= 1.0 / 32768.0
        if self.capture_id:
            # System audio captured by the app (app/system_audio.py) joins the page's microphone
            from app.system_audio import get_capture

            cap = get_capture(self.capture_id)
            if cap is not None:
                sys_part = cap.take_live(chunk.size)
                chunk[: sys_part.size] += sys_part
        with self._audio_lock:
            self._append(chunk)
            self.received += chunk.size / SR
        # Nothing decoded for long (steps fail or one hangs): only the last part is kept. Not while a
        # step runs: it cuts the buffer from its start when it ends
        if self.audio.size > 2 * LIVE_WINDOW_SEC * SR and self._busy.acquire(blocking=False):
            try:
                self._drop_to(LIVE_WINDOW_SEC / 2)
            finally:
                self._busy.release()
        self.touched = time.time()
        from app import idle_unload

        idle_unload.touch(captions=True)

    # -------------------------------------------------------------- decoding
    def phrases(self) -> bool:
        """Captions by VAD phrases (Russian with GigaAM: app/live_phrases.py), not by the sliding window."""
        if not self.onnx_model:
            return False
        from app import asr_onnx

        return asr_onnx.live_phrases(self.onnx_model)

    def follows_speech(self) -> bool:
        """In the window scheme with GigaAM / Parakeet the VAD follows the speech (live_phrases.SpeechFollow) at every
        step, whether the drafts of the phrase are on or not: about 0.2 ms a frame. Not for the Whisper captions
        (their own process)."""
        if not self.onnx_model or self._follow is False:
            return False
        from app import asr_onnx

        return asr_onnx.is_loaded(self.onnx_model)

    def _window_ran(self, cost: float) -> None:
        """A run of the window took `cost` seconds: the drafts off above DRAFTS_OFF_SEC, on again under DRAFTS_ON_SEC,
        and their share of the budget is what the window leaves of CAPTION_BUSY_SHARE."""
        self._window_cost = cost
        was = self._drafts_on
        if cost > DRAFTS_OFF_SEC:
            self._drafts_on = False
        elif cost < DRAFTS_ON_SEC:
            self._drafts_on = True
        if self._drafts_on != was:
            print(f"[live] phrase drafts {'on' if self._drafts_on else 'off'}: a run of the window took {cost:.2f} s",
                  flush=True)
        if self._follow:
            self._follow.pace.share = max(MIN_DRAFT_SHARE, CAPTION_BUSY_SHARE - cost / LIVE_STEP_SEC)

    def step(self) -> None:
        """Transcribes the undecided window (or the phrase being spoken) if enough new audio arrived and
        nothing else is running."""
        phrases = self.phrases()
        follow = not phrases and self.follows_speech()
        drafts = follow and self._drafts_on
        every = PHRASE_STEP_SEC if phrases or drafts else LIVE_STEP_SEC
        if self.received - self.last_run_at < every or not self._busy.acquire(blocking=False):
            return
        try:
            self.last_run_at = self.received
            if phrases:
                self._follow = None
                self._transcribe_phrases()
            else:
                self._ph = None
                if follow:
                    self._follow_speech()  # before the window cuts what is final: the VAD must have heard it
                # a slow window (a slow PC, on battery) runs less often: it never takes more than the budget
                if self.received - self.last_window_at >= max(LIVE_STEP_SEC, self._window_cost / CAPTION_BUSY_SHARE):
                    self.last_window_at = self.received
                    t = _clock()
                    self._transcribe_window()
                    self._window_ran(_clock() - t)
                elif drafts:
                    self._draft_phrase()
        except Exception as e:  # a failed step must not end the recording
            if str(e)[:200] != self.error:
                traceback.print_exc()
            self.error = str(e)[:200]
            # The audio of a failed window is not kept for later: the buffer would grow for the whole
            # recording (the saved file has everything; captions follow the speech as it goes)
            if self.audio.size > LIVE_WINDOW_SEC * SR:
                self._drop_to(LIVE_WINDOW_SEC / 2)
        finally:
            self._busy.release()

    def _drop_to(self, keep_sec: float) -> None:
        with self._audio_lock:
            cut = max(0, self.audio.size - int(keep_sec * SR))
            self._cut(cut)

    def _cut(self, cut: int) -> None:
        """Drops the first `cut` samples (call with _audio_lock held): what was appended meanwhile stays."""
        cut = min(cut, self._n)
        self._buf = self._buf[cut:]
        self._n -= cut
        self.base += cut
        self.offset = self.base / SR

    def _transcribe_window(self) -> None:
        window, base0 = self.audio, self.base
        win_sec = window.size / SR
        if win_sec < 0.8:
            return
        onnx_id = self.onnx_model
        if onnx_id:
            from app import asr_onnx

            if not asr_onnx.is_loaded(onnx_id):
                # Still loading (or installing) in the background: captions start once it is ready;
                # the audio meanwhile stays in the window, bounded by add_audio
                self.error = asr_onnx.preload_async(onnx_id)
                return
            segs = [_Seg(a, b, t) for a, b, t in asr_onnx.recognize_array(onnx_id, window)]
            language = asr_onnx.guess_language(" ".join(x.text for x in segs)) if segs else None
            prob = 1.0 if segs and not self.speech_lang else 0.0
        else:
            segs, language, prob = _caption_worker().transcribe(window, self.speech_lang)
        # One caption line per sentence (a phrase without pauses can hold several)
        from app.asr_onnx import _SENT_END, split_sentences_text

        from app import vocab

        rules = vocab.current()
        segs = [_Seg(a, b, vocab.fix_text(t, rules)) for x in segs
                for a, b, t in split_sentences_text(x.start, x.end, x.text.strip())]
        if self.speech_lang:
            self.lang = self.speech_lang
        elif language and prob > 0.5:
            self.lang = language
        self.error = ""
        force = win_sec > LIVE_WINDOW_SEC
        final_until = 0.0
        new_lines = []
        for i, s in enumerate(segs):
            # With GigaAM / Parakeet a sentence the speaker has moved on from is final at once (its
            # end is exact, from the word timings): the draft line then holds only the sentence
            # still being spoken and never splits in two on the screen
            moved_on = bool(onnx_id) and i + 1 < len(segs) and s.text.strip().endswith(_SENT_END)
            if moved_on or s.end <= win_sec - FINAL_MARGIN_SEC or (force and s.end <= win_sec - 0.3):
                new_lines.append({
                    "id": self._next_id, "text": s.text.strip(), "lang": self.lang,
                    "start": round(self.offset + s.start, 2), "end": round(self.offset + s.end, 2),
                    "translation": None,
                })
                self._next_id += 1
                final_until = s.end
            else:
                break
        if final_until > 0:
            with self._audio_lock:
                self._cut(int(final_until * SR))
        elif force:
            # Nothing ended in a long window (one endless phrase): keep only its last part
            with self._audio_lock:
                self._cut(int((win_sec - LIVE_WINDOW_SEC / 2) * SR))
        self._add_lines(new_lines)
        # Everything after the final phrases is the draft line
        self.partial = " ".join(s.text.strip() for s in segs[len(new_lines):]).strip()
        # kept for the drafts of the phrase being spoken until the next run (_draft_phrase), in samples of the stream
        self._win_draft = [(base0 + int(s.start * SR), base0 + int(s.end * SR), s.text.strip())
                           for s in segs[len(new_lines):] if s.text.strip()]
        if self._follow:
            self._follow.drafted_to = base0 + window.size
        tr = self.translator  # once: configure() in another request may set it to None meanwhile
        if tr:
            if new_lines:
                tr.add_lines(new_lines)
                # The draft translation belonged to the phrase that is final now: the next draft
                # must not be shown with it (the page keeps it on the final line until its own
                # translation arrives)
                tr.reset_draft()
            # The draft (revised several times while spoken) is translated only when the page shows
            # it; otherwise the model is left free for the final lines
            tr.set_draft(self.partial if self.draft else "")

    def _follow_speech(self) -> None:
        """The VAD over the new audio in the window scheme (live_phrases.SpeechFollow); its model is the Silero VAD
        of the phrases. If it cannot start, the window's draft goes on as before."""
        from app import asr_onnx, live_phrases as lp

        f = self._follow
        if f and f.cutter.pos < self.base:  # audio dropped before the VAD heard it: its state reset, its session kept
            f.vad.reset()
            share = f.pace.share
            f = self._follow = lp.SpeechFollow(self.base, f.vad)
            f.pace.share = share
        elif f is None:  # the first step
            try:
                f = self._follow = lp.SpeechFollow(self.base, lp.SileroStream(asr_onnx._vad_dir()))
            except Exception as e:
                print(f"[live] the drafts of the phrase are off: {e}", flush=True)
                self._follow = False
                return
        with self._audio_lock:
            audio, base = self.audio, self.base
        f.follow(audio, base)

    def _draft_phrase(self) -> None:
        """The draft line between the window's runs: the window's draft sentences that end before the phrase being
        spoken stay, and the phrase (from the start of a sentence of the window that reaches into it) is recognized
        alone, at the pace of live_phrases.DraftPace. The final lines come from the window as before."""
        from app import asr_onnx, live_phrases as lp, vocab

        f = self._follow
        span = f.target() if f else None
        if not span or not f.pace.due(self.received):
            return
        with self._audio_lock:
            audio, base = self.audio, self.base
        start, end = max(span[0], base), min(span[1], base + audio.size)
        keep = []
        for a, b, text in self._win_draft:
            if b <= base:
                continue
            if b <= start + int(lp.PAD_SEC * SR):
                keep.append(text)
                continue
            start = max(base, min(start, a))  # a sentence of the window reaching into the phrase: heard with it
            break
        if end - start < lp.MIN_SPEECH_SEC * SR:
            return
        phrase = asr_onnx.level(audio[start - base:end - base])
        parts = f.pace.run(self.received, lambda: asr_onnx.recognize_phrase(self.onnx_model, phrase))
        f.drafted_to = end
        text = vocab.fix_text(" ".join(t for _, _, t in parts), vocab.current()).strip()
        if not text:
            return  # nothing heard: the window's draft stays
        self.partial = " ".join(keep + [text])
        tr = self.translator  # once: configure() in another request may set it to None meanwhile
        if tr:
            tr.set_draft(self.partial if self.draft else "")

    def _transcribe_phrases(self) -> None:
        """Russian captions by VAD phrases (app/live_phrases.py): the VAD goes over the new audio; a phrase that
        ended (a pause of 0.5 s, or 20 s of speech without one) is recognized once and its sentences are final;
        the phrase still being spoken is the draft, recognized again every 0.3 s or more (live_phrases.DraftPace)."""
        from app import asr_onnx, live_phrases as lp, vocab

        onnx_id = self.onnx_model
        if not asr_onnx.is_loaded(onnx_id):
            self.error = asr_onnx.preload_async(onnx_id)  # the audio waits in the buffer, bounded by add_pcm16
            return
        ph = self._ph
        if ph is None or min(ph.keep_from(), ph.levelled_to) < self.base:
            # the first step, or the audio waited for the model so long that its start was dropped: the VAD made
            # once (an InferenceSession), its state reset for the new start
            vad = ph.vad if ph is not None else lp.SileroStream(asr_onnx._vad_dir())
            if ph is not None:
                vad.reset()
            ph = self._ph = lp.PhraseState(self.base, vad)
        with self._audio_lock:  # the new audio levelled in place: the VAD and the model hear the same
            i = ph.levelled_to - self.base
            new = ph.level(self.audio[i:])
            self.audio[i:i + new.size] = new
            ph.levelled_to += new.size
            audio, base = self.audio, self.base  # only this step cuts it: the indices below stay valid
        ended = []
        c = ph.cutter
        while c.pos + lp.FRAME <= ph.levelled_to:
            frame = audio[c.pos - base:c.pos - base + lp.FRAME]
            cut = c.push(ph.vad.prob(frame))
            if cut:
                ended.append(cut)
        if self.speech_lang:
            self.lang = self.speech_lang
        self.error = ""
        rules = vocab.current()
        new_lines = []
        for a, b, forced in ended:
            parts = []
            # the tail of a forced cut shorter than a word: not recognized at all
            heard = [] if ph.after_cut and b - a < lp.MIN_SPEECH_SEC * SR else \
                asr_onnx.recognize_phrase(onnx_id, audio[a - base:b - base])
            for k, (s, e, t) in enumerate(heard):
                text = vocab.fix_text(t, rules).strip()
                if ph.seam and k == 0:  # the seam of a forced cut: the word cut in half is not heard twice
                    text = lp.drop_seam_repeat(ph.seam, text)
                if text:
                    parts.append((s, e, text))
            if ph.after_cut and parts and lp.tail_fragment(b - a, " ".join(t for _, _, t in parts)):
                parts = []  # only the tail of the cut word: no line of one letter
            ph.after_cut = forced
            ph.seam = lp.last_word(parts[-1][2]) if forced and parts else ""
            for s, e, text in parts:
                if not self.speech_lang:
                    self.lang = asr_onnx.guess_language(text)
                new_lines.append({
                    "id": self._next_id, "text": text, "lang": self.lang,
                    "start": round(a / SR + s, 2), "end": round(a / SR + e, 2), "translation": None,
                })
                self._next_id += 1
        if ended:
            ph.pace.restart()  # the first draft of the next phrase as soon as it has enough speech
            self.partial = ""
        if c.start is None:
            self.partial = ""
        elif c.pos - c.start >= lp.MIN_DRAFT_SEC * SR and c.last_speech > ph.drafted_to and ph.pace.due(self.received):
            phrase = audio[c.start - base:c.pos - base]
            ph.drafted_to = c.pos
            parts = ph.pace.run(self.received, lambda: asr_onnx.recognize_phrase(onnx_id, phrase))
            draft = vocab.fix_text(" ".join(t for _, _, t in parts), rules).strip()
            self.partial = lp.drop_seam_repeat(ph.seam, draft) if ph.seam and c.continued else draft
        with self._audio_lock:
            self._cut(max(0, ph.keep_from() - self.base))
        self._add_lines(new_lines)
        tr = self.translator  # once: configure() in another request may set it to None meanwhile
        if tr:
            if new_lines:
                tr.add_lines(new_lines)
                tr.reset_draft()
            tr.set_draft(self.partial if self.draft else "")

    def configure(self, translate_to: Optional[str], speed: Optional[str], speech_lang: Optional[str] = None,
                  pair: Optional[List[str]] = None) -> None:
        """Changes the translation (and the speech language) while recording; the last lines are
        translated again."""
        from app.live_translate import LiveTranslator

        if speech_lang is not None:
            self.speech_lang = None if speech_lang in ("", "auto") else speech_lang
            if self.speech_lang:
                self.lang = self.speech_lang
            self.onnx_model = caption_onnx_model(get_all_settings(), self.speech_lang)
        if speed in ("quality", "fast") and speed != self.speed:
            self.speed = speed
            self.translate_choice = _translate_choice(get_all_settings(), speed)
        if not translate_to:
            if self.translator:
                self.translator.stop()
            self.translator, self.translate_to = None, None
            return
        new_pair = list(pair)[:2] if pair else self.pair
        changed = translate_to != self.translate_to or (translate_to == "auto" and new_pair != self.pair)
        self.translate_to = translate_to
        self.pair = new_pair
        if self.translator is None:
            self.translator = LiveTranslator(lambda: self.lang, translate_to, self.speed, self.pair)
            self.translator.add_lines([ln for ln in self.lines[-20:]])
            from app import idle_unload

            idle_unload.captions_started()  # the translation turned on: the card is freed for its model
        else:
            self.translator.configure(translate_to, speed, retranslate=self.lines[-20:] if changed else None, pair=self.pair)

    def _add_lines(self, new_lines: List[Dict[str, Any]]) -> None:
        """Final lines at the end; the oldest beyond LINES_KEPT go (in steps of 500, not on every line)."""
        if not new_lines:
            return
        self.lines.extend(new_lines)
        if len(self.lines) > LINES_KEPT + 500:
            del self.lines[:-LINES_KEPT]

    def _note_changes(self) -> None:
        """The recent lines that are new or got a translation or a target language since the last look take the next
        version (call with _state_lock held)."""
        recent = self.lines[-RECENT_LINES:]
        for ln in recent:
            mark = (ln.get("translation"), ln.get("target"))
            if ln["id"] not in self._seen or self._seen[ln["id"]] != mark:
                self._seen[ln["id"]] = mark
                self._version += 1
                self._changed[ln["id"]] = self._version
        if len(self._seen) > 2 * RECENT_LINES and recent:
            first = recent[0]["id"]
            self._seen = {k: v for k, v in self._seen.items() if k >= first}
            self._changed = {k: v for k, v in self._changed.items() if k >= first}

    # -------------------------------------------------------------- out
    def state(self, since_id: int = 0, version: Optional[int] = None) -> Dict[str, Any]:
        """The answer to the page. version: the one the page has (from its last answer): only the lines changed since
        (new, translated, with their target language) — this answer goes out about four times a second. Without it
        (the start, a change of settings, an older page): the new lines, the recent ones waiting for a translation
        and the recent translations, as before."""
        tr = self.translator  # once: configure() in another request may set it to None meanwhile
        with self._state_lock:
            self._note_changes()
            now = self._version
            if version is not None:
                lines = [ln for ln in self.lines[-RECENT_LINES:] if self._changed.get(ln["id"], 0) > version]
                translations = {ln["id"]: ln["translation"] for ln in lines if ln["translation"]}
                targets = {ln["id"]: ln.get("target") for ln in lines if ln.get("target")}
            else:
                recent = self.lines[-RECENT_LINES:]
                lines = [ln for ln in recent if ln["id"] > since_id or (tr and ln["translation"] is None)]
                translations = {ln["id"]: ln["translation"] for ln in self.lines[-60:] if ln["translation"]}
                targets = {ln["id"]: ln.get("target") for ln in recent if ln.get("target")}
            lines = [dict(ln) for ln in lines]  # a copy: the translator fills the line in another thread
        return {
            "session": self.id,
            "version": now,
            "lang": self.lang,
            "speech_lang": self.speech_lang or "auto",
            "lines": lines,
            "translations": translations,
            # The language each line went into (differs per line with translate_to="auto")
            "targets": targets,
            "partial_target": tr.draft_target if tr else "",
            "partial": self.partial,
            "partial_translation": tr.draft_translation if tr else "",
            "translation_ready": bool(tr and tr.ready),
            "error": self.error or (tr.error if tr else ""),
            "caption_model": self.caption_label(),
            "caption_choice": self.caption_choice,
            "translate_choice": self.translate_choice,
            "translate_model": self.translate_label(),
        }

    def set_caption_model(self, value: str) -> None:
        """The caption model chosen in the studio ("auto", GigaAM / Parakeet or a Whisper model); it is
        the same setting as in Settings, so the next recording keeps it."""
        from app.database import update_settings
        from app.settings_schema import clean

        value = clean("live_whisper_model", value or "auto") or "auto"  # ValueError for a model not in the catalog
        update_settings({"live_whisper_model": value})
        self.caption_choice = value
        settings = get_all_settings()
        self.onnx_model = caption_onnx_model(settings, self.speech_lang)
        if self.onnx_model:
            from app import asr_onnx

            asr_onnx.preload_async(self.onnx_model)
        elif _worker is not None and _worker.proc is not None:
            from app.hardware import get_hardware_info

            if _worker.model_name != caption_model(settings, get_hardware_info()):
                with _worker.lock:
                    _worker._kill()  # started again with the new model on the next window

    def set_translate_model(self, model: Optional[str], speed: Optional[str] = None) -> None:
        """The translation model chosen in the studio for «Качество» or «Скорость» (the mode in use, or `speed`);
        "" is «Авто». It is the same setting as Settings → «Модели перевода», so the next recordings keep it."""
        from app.database import update_settings
        from app.live_translate import CHOICE_KEYS
        from app.settings_schema import clean

        mode = speed if speed in CHOICE_KEYS else self.speed
        key = CHOICE_KEYS[mode]
        value = clean(key, model or "")  # ValueError for a name Ollama cannot have
        update_settings({key: value})
        self.speed = mode
        self.translate_choice = value
        if self.translator:
            if speed in CHOICE_KEYS:
                self.translator.configure(speed=speed)
            self.translator.reload_model()

    def caption_label(self) -> str:
        """The model writing the captions now, for the studio."""
        if self.onnx_model:
            from app.asr_onnx import ONNX_MODELS

            return ONNX_MODELS[self.onnx_model]["name"]
        from app.model_manager import format_whisper_model_name

        name = _worker.model_name if _worker is not None and _worker.proc is not None else ""
        return format_whisper_model_name(name) if name else "Whisper"

    def translate_label(self) -> str:
        model = getattr(self.translator, "_model", None)  # None without a translator (read once)
        if not model:
            return ""
        from app.ollama_client import format_llm_model_name

        return format_llm_model_name(model)


def start_session(lang: Optional[str], translate_to: Optional[str], capture_id: Optional[str] = None,
                  speed: str = "quality", pair: Optional[List[str]] = None) -> LiveSession:
    _drop_idle()
    s = LiveSession(lang, translate_to, capture_id, speed, pair)
    with _sessions_lock:
        _sessions[s.id] = s
    # Load the caption model now, so the first captions do not wait for it
    if s.onnx_model:
        from app import asr_onnx

        asr_onnx.preload_async(s.onnx_model)
    else:
        threading.Thread(target=_caption_worker().preload, daemon=True).start()
    from app import idle_unload

    idle_unload.captions_started()  # what the captions do not use leaves the memory (app/idle_unload.py)
    return s


def active_session_count() -> int:
    """Caption sessions that received audio recently (a closed window's session drops out)."""
    _drop_idle()
    with _sessions_lock:
        return len(_sessions)


def caption_onnx_model(settings: Dict[str, str], speech_lang: Optional[str]) -> Optional[str]:
    """GigaAM / Parakeet for live captions, or None for Whisper. They run in this process on the CPU
    (ONNX Runtime does not abort the process like CUDA can), so they leave the GPU to the queue.
    "auto": GigaAM for Russian, Parakeet for its other languages and for "auto" speech (it is
    multilingual), Whisper when neither fits or is downloaded."""
    from app import asr_onnx

    chosen = (settings.get("live_whisper_model") or "auto").strip()
    lang = (speech_lang or "")[:2] or None
    if asr_onnx.is_onnx_model(chosen):
        return chosen if asr_onnx.is_installed(chosen) and asr_onnx.supports_language(chosen, lang) else None
    if chosen != "auto":
        return None
    order = ["gigaam-v3", "parakeet-v3"] if lang == "ru" else ["parakeet-v3"]
    return next((m for m in order if asr_onnx.is_installed(m) and asr_onnx.supports_language(m, lang)), None)


def caption_model(settings: Dict[str, str], hw: Dict[str, Any]) -> str:
    """The Whisper model for live captions. "auto": Turbo if downloaded (lighter and faster than Pro;
    the saved file is transcribed again by the main model anyway), otherwise the main model."""
    from app.model_manager import is_whisper_model_installed

    main = settings.get("whisper_model") or "large-v3-turbo"
    from app.asr_onnx import is_onnx_model

    if is_onnx_model(main):
        # Captions stay on Whisper (they are decoded in short windows by app/live_worker.py)
        main = next((m for m in ("large-v3-turbo", "large-v3") if is_whisper_model_installed(m)), "large-v3-turbo")
    chosen = (settings.get("live_whisper_model") or "auto").strip()
    if is_onnx_model(chosen):
        chosen = "auto"  # the Whisper fallback when GigaAM / Parakeet does not fit the language
    if chosen != "auto":
        return chosen if is_whisper_model_installed(chosen) else main
    return "large-v3-turbo" if is_whisper_model_installed("large-v3-turbo") else main


def translate_models_changed() -> None:
    """Settings → «Модели перевода» changed: the running captions translate with the model now saved for their mode."""
    with _sessions_lock:
        sessions = list(_sessions.values())
    settings = get_all_settings()
    for s in sessions:
        s.translate_choice = _translate_choice(settings, s.speed)
        if s.translator:
            s.translator.reload_model()


def get_session(session_id: str) -> Optional[LiveSession]:
    with _sessions_lock:
        return _sessions.get(session_id)


def stop_session(session_id: str) -> None:
    with _sessions_lock:
        s = _sessions.pop(session_id, None)
        last = s is not None and not _sessions
    if s and s.translator:
        s.translator.stop()
    if last:
        _captions_ended()


def _captions_ended() -> None:
    """The last caption session ended: its models go a minute later unless the app is used (app/idle_unload.py),
    and a transcription that waited for the captions starts now (transcriber.waits_for_captions)."""
    try:
        from app import transcriber

        transcriber.wake_queue()
    except Exception:
        traceback.print_exc()
    try:
        from app import idle_unload

        idle_unload.work_done("live captions ended")
    except Exception:
        traceback.print_exc()


def stop_all() -> int:
    """Every caption session ends (app/economy.py: recording only); the page sees its session gone."""
    with _sessions_lock:
        ids = list(_sessions)
    for sid in ids:
        stop_session(sid)
    return len(ids)


def _drop_idle() -> None:
    """Sessions whose page stopped sending audio (closed, reloaded, crashed) end, with their
    translator thread."""
    now = time.time()
    with _sessions_lock:
        dropped = [_sessions.pop(k) for k, s in list(_sessions.items()) if now - s.touched > SESSION_IDLE_SEC]
        last = bool(dropped) and not _sessions
    for s in dropped:
        if s.translator:
            s.translator.stop()
    if last:
        _captions_ended()


def has_sessions() -> bool:
    _drop_idle()
    with _sessions_lock:
        return bool(_sessions)


def model_in_use(model_id: str) -> bool:
    """A live session gives its captions with this GigaAM / Parakeet model now."""
    _drop_idle()
    with _sessions_lock:
        return any(getattr(s, "onnx_model", None) == model_id for s in _sessions.values())


def onnx_models_in_use() -> Set[str]:
    """The GigaAM / Parakeet models the open caption sessions recognize with (on the processor)."""
    with _sessions_lock:
        return {s.onnx_model for s in _sessions.values() if getattr(s, "onnx_model", None)}


def translator_models() -> Set[str]:
    """The Ollama models the open caption sessions translate with, or are about to (app/idle_unload.py keeps them)."""
    with _sessions_lock:
        translators = [s.translator for s in _sessions.values() if s.translator]
    out: Set[str] = set()
    for tr in translators:
        try:
            model = tr.wanted_model()
        except Exception:
            traceback.print_exc()
            model = None
        if model:
            out.add(model)
    return out
