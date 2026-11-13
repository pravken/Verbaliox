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
from typing import Dict, Optional, Tuple

import numpy as np

SR = 48000
BLOCK = SR // 10  # 100 ms

_captures: Dict[str, "SystemCapture"] = {}
_lock = threading.Lock()


GAP_SEC = 0.5     # the loopback gave nothing this long (nothing played): the pause is written as silence
LOST_MIN_SEC = 0.03  # Windows said data was lost: a gap of this much is filled already
AHEAD_MAX_SEC = 0.3  # the track never runs further ahead of the clock than this


def place_block(elapsed_sec: float, written: int, block: int, waited_sec: float, lost: bool) -> Tuple[int, int]:
    """(samples of silence to put before a block just received, samples to drop from its start), so
    the system track keeps to the clock the microphone keeps to.

    Silence goes in only where sound really is missing: Windows gave the loopback nothing for a while
    (nothing played: the call to read it waited), or Windows said data was lost («data discontinuity»,
    the app was too busy to read it in time). A block that only came late (the app was busy, the
    data waited in Windows' buffer) gets no silence: written for it, the track ran 2 s ahead in 7 s,
    and the same voice came twice in the mix. Lost data left without silence made the track run ahead
    in small steps, and the echo's delay jumped all through a meeting. A track ahead of the clock
    anyway drops what is too much."""
    behind = int(elapsed_sec * SR) - written - block
    if behind > 0 and ((lost and behind > LOST_MIN_SEC * SR) or (waited_sec > GAP_SEC and behind > GAP_SEC * SR)):
        return behind, 0
    if behind < -AHEAD_MAX_SEC * SR:
        return 0, min(block, -behind - int(0.1 * SR))
    return 0, 0


def silence_to_add(elapsed_sec: float, written: int, block: int) -> int:
    """The silence before a block that waited (nothing played) — place_block with a long wait."""
    return place_block(elapsed_sec, written, block, elapsed_sec, False)[0]


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
        self.lost = 0             # blocks Windows said it lost data before
        self.dropped = 0          # samples left out: the track was ahead of the clock
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
                import warnings

                while not self._stop.is_set():
                    asked = time.time()
                    # Windows marks data it dropped (the app did not read in time): soundcard warns of it;
                    # caught here (it is a gap to fill) and not written to the log thousands of times
                    with warnings.catch_warnings(record=True) as caught:
                        warnings.simplefilter("always")
                        block = rec.record(numframes=BLOCK)
                    lost = any("discontinuity" in str(w.message) for w in caught)
                    if lost:
                        self.lost += 1
                    if block.ndim == 1:
                        block = np.stack([block, block], axis=1)
                    now = time.time()
                    gap, drop = place_block(now - self.started_at, written, len(block), now - asked, lost)
                    if drop:
                        block = block[drop:]
                        self.dropped += drop
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
                  f"{self.padded / SR:.1f} s of it silence for {self.gaps} pause(s); Windows lost data {self.lost} time(s), "
                  f"{self.dropped / SR:.2f} s left out (ahead of the clock)", flush=True)


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
