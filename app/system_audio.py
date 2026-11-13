"""
Recording of the computer's own sound (what plays in the speakers) without the browser.

In the page, system audio could only come from getDisplayMedia, which asks to pick a window or
screen and to tick "share audio" every time. Here it is captured in the app through WASAPI
loopback of the default output device (the `soundcard` package): no prompt at all. The page still
records the microphone; when recording stops both are mixed into one file (FFmpeg) and queued for
transcription like any import. Live captions get this sound mixed into the page's microphone audio.
"""

import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Dict, Optional

import numpy as np

SR = 48000
BLOCK = SR // 10  # 100 ms

_captures: Dict[str, "SystemCapture"] = {}
_lock = threading.Lock()


GAP_SEC = 0.5  # the loopback this far behind the clock: the silence it did not deliver is written


def silence_to_add(elapsed_sec: float, written: int, block: int) -> int:
    """Samples of silence that belong before a block just received. Windows gives a loopback nothing
    while nothing plays; without them every pause was cut out of the system track, which then ran
    ahead of the microphone and the same voices came twice in the mix."""
    behind = int(elapsed_sec * SR) - written - block
    return behind if behind > GAP_SEC * SR else 0


class SystemCapture:
    def __init__(self, path: Path):
        self.id = uuid.uuid4().hex
        self.path = path
        self.level = 0.0          # RMS of the last block, for the record meter
        self.error = ""
        self.started_at = 0.0
        self.written = 0          # samples in the file
        self.padded = 0           # of them, silence put for pauses the loopback did not deliver
        self.gaps = 0
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._live = np.zeros(0, dtype=np.float32)  # 16 kHz mono, not yet taken by live captions
        self._live_lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True, name="system_audio")

    def start(self) -> None:
        self._thread.start()
        if not self._ready.wait(5) or self.error:
            # Not started in time (or failed): the thread is told to stop and its file goes — a device
            # that came up later recorded into a file nothing could stop or finish
            error = self.error or "захват системного звука не начался"
            self._stop.set()
            self._thread.join(timeout=2)
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass
            raise RuntimeError(error)

    def _run(self) -> None:
        import soundcard as sc
        import soundfile as sf

        try:
            speaker = sc.default_speaker()
            loopback = sc.get_microphone(id=str(speaker.name), include_loopback=True)
            with sf.SoundFile(str(self.path), "w", samplerate=SR, channels=2, subtype="PCM_16") as out, \
                    loopback.recorder(samplerate=SR, channels=2, blocksize=BLOCK) as rec:
                self.started_at = time.time()
                self._ready.set()
                written = 0
                while not self._stop.is_set():
                    block = rec.record(numframes=BLOCK)
                    if block.ndim == 1:
                        block = np.stack([block, block], axis=1)
                    gap = silence_to_add(time.time() - self.started_at, written, len(block))
                    if gap:
                        out.write(np.zeros((gap, 2), dtype=np.float32))
                        written += gap
                        self.padded += gap
                        self.gaps += 1
                        if self._live_wanted():
                            with self._live_lock:
                                self._live = np.concatenate([self._live, np.zeros(gap // 3, dtype=np.float32)])[-16000 * 30:]
                    out.write(block)
                    written += len(block)
                    self.written = written
                    mono = block.mean(axis=1).astype(np.float32)
                    self.level = float(np.sqrt(np.mean(mono ** 2))) if mono.size else 0.0
                    if self._live_wanted():
                        with self._live_lock:
                            # 48 kHz -> 16 kHz by averaging groups of three samples (enough for captions)
                            n = mono.size // 3 * 3
                            self._live = np.concatenate([self._live, mono[:n].reshape(-1, 3).mean(axis=1)])[-16000 * 30:]
        except Exception as e:
            traceback.print_exc()
            self.error = f"Не удалось записать системный звук: {e}"[:300]
            self._ready.set()

    _live_taken_at = 0.0  # when live captions last took the sound (set on the instance)

    def _live_wanted(self) -> bool:
        """Live captions take the sound now (within a few seconds): without them the 30 s buffer was
        copied ten times a second for the whole recording."""
        return time.time() - self._live_taken_at < 5.0

    def take_live(self, count: int) -> np.ndarray:
        """Up to `count` samples (16 kHz mono) captured since the last call, for live captions. What
        piled up beyond half a second (captions switched on during the recording: up to 30 s) is
        dropped, so the system sound joins the microphone's chunk it was heard with, not late."""
        self._live_taken_at = time.time()
        with self._live_lock:
            if self._live.size - count > 8000:  # behind by more than the jitter of the chunks: the newest
                self._live = self._live[self._live.size - count:]
            out, self._live = self._live[:count], self._live[count:]
        return out

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        if self.started_at:
            # what lines the tracks up later: the file against the clock, and the silence put in it
            print(f"[system audio] {self.written / SR:.1f} s written over {time.time() - self.started_at:.1f} s, "
                  f"{self.padded / SR:.1f} s of it silence for {self.gaps} pause(s)", flush=True)


def start_capture(path: Path) -> SystemCapture:
    cap = SystemCapture(path)
    cap.start()
    with _lock:
        _captures[cap.id] = cap
    return cap


def get_capture(capture_id: str) -> Optional[SystemCapture]:
    with _lock:
        return _captures.get(capture_id)


def finish_capture(capture_id: str) -> Optional[SystemCapture]:
    with _lock:
        cap = _captures.pop(capture_id, None)
    if cap:
        cap.stop()
    return cap
