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
DEVICE_CHECK_SEC = 2.0  # how often the output device Windows uses is looked at


class _Silence:
    """Stands for the loopback while there is no output device at all: a block of silence at the pace
    of the clock, so the recording goes on and the next device is looked for."""

    def record(self, numframes: int) -> np.ndarray:
        time.sleep(numframes / SR)
        return np.zeros((numframes, 2), dtype=np.float32)

    def __exit__(self, *a) -> None:
        pass


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
        self.switches = 0         # times the recording moved to another output device
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

    def _open(self, sc):
        """The loopback of the output device Windows uses now (by its id: two devices may share a name)."""
        speaker = sc.default_speaker()
        loopback = sc.get_microphone(id=str(speaker.id), include_loopback=True)
        return str(speaker.id), str(speaker.name), loopback.recorder(samplerate=SR, channels=2, blocksize=BLOCK)

    def _run(self) -> None:
        import warnings

        import soundcard as sc
        import soundfile as sf

        rec = None
        try:
            device, name, rec = self._open(sc)
            rec.__enter__()
            # RF64: a plain WAV ends at 4 GB, about 6 hours of this sound (FFmpeg and soundfile read both)
            with sf.SoundFile(str(self.path), "w", samplerate=SR, channels=2, subtype="PCM_16", format="RF64") as out:
                self.started_at = time.time()
                self._ready.set()
                print(f"[system audio] recording the output device «{name}»", flush=True)
                written, checked, switched = 0, time.time(), False
                while not self._stop.is_set():
                    # The output device changed (a headset plugged in mid-call, the call moved to it): the
                    # loopback of the old one gave silence for the rest of the meeting. Looked at every 2 s
                    if time.time() - checked > DEVICE_CHECK_SEC:
                        checked = time.time()
                        try:
                            now_id = str(sc.default_speaker().id)
                        except Exception:
                            now_id = device
                        if now_id != device:
                            device, switched = self._switch(sc, rec, device)
                            rec = self._rec
                    asked = time.time()
                    # Windows marks data it dropped (the app did not read in time): soundcard warns of it;
                    # caught here (it is a gap to fill) and not written to the log thousands of times
                    try:
                        with warnings.catch_warnings(record=True) as caught:
                            warnings.simplefilter("always")
                            block = rec.record(numframes=BLOCK)
                    except Exception as e:  # the device went away (unplugged): the next default one
                        print(f"[system audio] the output device stopped: {e}", flush=True)
                        time.sleep(0.5)
                        device, switched = self._switch(sc, rec, device, force=True)
                        rec = self._rec
                        continue
                    lost = switched or any("discontinuity" in str(w.message) for w in caught)
                    switched = False
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
        finally:
            self._close(rec)

    _rec = None

    @staticmethod
    def _close(rec) -> None:
        if rec is not None:
            try:
                rec.__exit__(None, None, None)
            except Exception:
                pass

    def _switch(self, sc, rec, device: str, force: bool = False):
        """The loopback moved to the output device Windows uses now. (device id, True when it moved: the
        time it took is then filled with silence, so the track keeps to the clock). Without a device to
        move to, the old recorder stays (force: it is gone, the next try comes after a pause)."""
        self._rec = rec
        try:
            new_id, name, new_rec = self._open(sc)
            new_rec.__enter__()
        except Exception as e:
            if force:
                self._close(rec)
                self._rec = _Silence()
                self.switches += 1
                print(f"[system audio] no output device to record ({e}); silence until one comes", flush=True)
                return "", True
            return device, False
        self._close(rec)
        self._rec = new_rec
        self.switches += 1
        print(f"[system audio] the output device changed: now «{name}»", flush=True)
        return new_id, True

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
                  f"{self.dropped / SR:.2f} s left out (ahead of the clock), {self.switches} change(s) of the output device", flush=True)


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


def repair_rf64(path: Path) -> bool:
    """A recording the app could not close (a crash, a power cut) has an RF64 header that still says
    «no data yet»: FFmpeg then decodes 0 seconds. The sizes are set from the file's own length, so it is
    read whole. True when something was set right."""
    import struct

    try:
        size = path.stat().st_size
        with open(path, "r+b") as f:
            head = f.read(12)
            if len(head) < 12 or head[:4] != b"RF64" or head[8:12] != b"WAVE":
                return False
            pos, ds64_at, data_at, block = 12, -1, -1, 4
            while pos + 8 <= size:
                f.seek(pos)
                cid, csize = struct.unpack("<4sI", f.read(8))
                if cid == b"ds64":
                    ds64_at = pos + 8
                elif cid == b"fmt ":
                    f.seek(pos + 8 + 12)
                    block = struct.unpack("<H", f.read(2))[0] or 4
                elif cid == b"data":
                    data_at = pos + 8
                    break
                pos += 8 + csize + (csize & 1)
            if ds64_at < 0 or data_at < 0:
                return False
            data = size - data_at
            data -= data % block
            f.seek(ds64_at)
            old = struct.unpack("<QQQ", f.read(24))
            new = (size - 8, data, data // block)
            if old == new:
                return False
            f.seek(ds64_at)
            f.write(struct.pack("<QQQ", *new))
        print(f"[system audio] {path.name}: header set from the file ({data / block / SR:.1f} s)", flush=True)
        return True
    except (OSError, struct.error) as e:
        print(f"[system audio] {path.name}: header not repaired: {e}", flush=True)
        return False
