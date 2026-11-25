"""
Live captions by VAD phrases (bench-report/asr-2026-11.md, item 3): for Russian with GigaAM v3 e2e-CTC int8.

Instead of recognizing a sliding window of up to 20 s again and again (app/live.py), the Silero VAD follows the
stream frame by frame (32 ms) and only the phrase being spoken is recognized: from the start of speech, as a
draft at most every DRAFT_SEC, and once more as the final text after a pause of END_PAUSE_SEC. In the bench this
gave the final text in 0.9–1.1 s instead of 3–4 s, with a lower WER, a seventh of the processor load and 0.44 GB of
memory instead of 2.9.

Speech without pauses is cut at MAX_PHRASE_SEC, where the VAD hears the speech weakest in the last
CUT_SEARCH_SEC (most often a breath or a gap between words). The next phrase starts exactly there: no audio is
recognized twice and none is left out (the duplicated and lost words at forced cuts of other programs,
Meetily issue #756).

The stream is levelled as the recordings are (app.asr_onnx.level), from the loudest part of the last 10 s:
quiet speech is otherwise taken for silence by the VAD.
"""

from collections import deque
from pathlib import Path
from typing import Any, List, Optional, Tuple

import numpy as np

SR = 16000
FRAME = 512          # samples of one VAD frame (32 ms)
CONTEXT = 64         # samples of the frame before, which the Silero VAD sees too
START_PROB = 0.5     # speech starts at this probability
KEEP_PROB = 0.35     # and goes on while above this
END_PAUSE_SEC = 0.5  # a pause this long ends the phrase
MIN_SPEECH_SEC = 0.25  # a shorter sound is noise
MAX_PHRASE_SEC = 20.0  # speech without a pause is cut here
CUT_SEARCH_SEC = 4.0   # the forced cut goes where the speech is weakest in the last seconds
PAD_SEC = 0.1          # audio kept before the speech starts and after it ends
DRAFT_SEC = 1.2        # a draft at most this often
MIN_DRAFT_SEC = 0.5    # and not for less speech than this


class PhraseCutter:
    """Speech probabilities frame by frame -> phrases as (start, end, forced) in samples of the stream. The
    phrases never overlap, and a forced cut leaves no gap: the next phrase starts where the cut one ends."""

    def __init__(self, start_at: int = 0):
        self.pos = start_at        # the end of the last frame given
        self.floor = start_at      # no phrase starts before this (the end of the last one)
        self.start: Optional[int] = None
        self.last_speech = start_at
        self.silence = 0
        self.continued = False     # this phrase goes on from a forced cut: kept however short
        self.probs: List[Tuple[int, float]] = []  # (frame start, probability) of the phrase going on

    def push(self, p: float) -> Optional[Tuple[int, int, bool]]:
        frame_start = self.pos
        self.pos += FRAME
        pad = int(PAD_SEC * SR)
        if self.start is None:
            if p >= START_PROB:
                self.start = max(self.floor, frame_start - pad)
                self.last_speech, self.silence, self.continued = self.pos, 0, False
                self.probs = [(frame_start, p)]
            return None
        self.probs.append((frame_start, p))
        if p >= KEEP_PROB:
            self.silence, self.last_speech = 0, self.pos
        else:
            self.silence += FRAME
        if self.silence >= END_PAUSE_SEC * SR:
            start, self.start, self.probs = self.start, None, []
            if self.last_speech - start < MIN_SPEECH_SEC * SR and not self.continued:
                return None  # a click, a cough: no phrase
            end = min(self.pos, self.last_speech + pad)
            self.floor = end
            return start, end, False
        if self.pos - self.start >= MAX_PHRASE_SEC * SR:
            cut = self._cut_point()
            start, self.start, self.floor, self.continued = self.start, cut, cut, True
            self.probs = [(s, q) for s, q in self.probs if s >= cut]
            return start, cut, True
        return None

    def _cut_point(self) -> int:
        """Where speech without a pause is cut: the middle of the frame with the weakest speech in the last
        CUT_SEARCH_SEC, the latest one of equals (the cut phrase keeps as much as it can)."""
        lo = max(self.start + int(MAX_PHRASE_SEC * SR / 2), self.pos - int(CUT_SEARCH_SEC * SR))
        frames = [(q, -s, s) for s, q in self.probs if s >= lo]
        if not frames:
            return self.pos
        _, _, s = min(frames)
        return min(self.pos, s + FRAME // 2)


class SileroStream:
    """The Silero VAD of the app's models folder, one frame at a time (one thread, not spinning)."""

    def __init__(self, vad_dir: Path):
        import onnxruntime as ort

        from app.asr_onnx import _cpu_options

        files = sorted(p for p in Path(vad_dir).glob("*.onnx") if "int8" not in p.name and "16k" not in p.name)
        if not files:
            raise RuntimeError("Модель обнаружения речи Silero не найдена")
        self.sess = ort.InferenceSession(str(files[0]), _cpu_options(1), providers=["CPUExecutionProvider"])
        self.inputs = [i.name for i in self.sess.get_inputs()]
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.context = np.zeros((1, CONTEXT), dtype=np.float32)

    def prob(self, frame: np.ndarray) -> float:
        x = np.concatenate([self.context, frame.reshape(1, -1).astype(np.float32)], axis=1)
        feeds = {}
        for name in self.inputs:
            if name == "input":
                feeds[name] = x
            elif name == "state":
                feeds[name] = self.state
            elif name == "sr":
                feeds[name] = np.array(SR, dtype=np.int64)
        out = self.sess.run(None, feeds)
        self.state = out[1]
        self.context = x[:, -CONTEXT:]
        return float(np.asarray(out[0]).reshape(-1)[0])


class StreamLevel:
    """app.asr_onnx.level while the audio arrives: the gain follows the loudest part of the last 10 s (it drops at
    once, so nothing clips, and rises over a few pieces)."""

    def __init__(self) -> None:
        self.peaks: "deque[Tuple[int, float]]" = deque()
        self.gain = 1.0

    def __call__(self, piece: np.ndarray) -> np.ndarray:
        from app.asr_onnx import LEVEL_WINDOW_SEC, MAX_GAIN, QUIET_PEAK, SILENT_PEAK

        if not piece.size:
            return piece
        self.peaks.append((piece.size, float(np.percentile(np.abs(piece), 99.9))))
        while sum(n for n, _ in self.peaks) > LEVEL_WINDOW_SEC * SR and len(self.peaks) > 1:
            self.peaks.popleft()
        p = max(x for _, x in self.peaks)
        target = min(0.9 / p, MAX_GAIN) if SILENT_PEAK < p < QUIET_PEAK else 1.0
        self.gain = target if target < self.gain else self.gain + (target - self.gain) * 0.5
        return np.clip(piece * self.gain, -1.0, 1.0).astype(np.float32)


class PhraseState:
    """What a caption session keeps between steps in this mode."""

    def __init__(self, start_at: int, vad: Any):
        self.cutter = PhraseCutter(start_at)
        self.vad = vad
        self.level = StreamLevel()
        self.levelled_to = start_at  # the stream is levelled in place up to here
        self.last_draft = 0.0        # seconds received when the last draft was made

    def keep_from(self) -> int:
        """The first sample still needed: the start of the phrase going on, or a little before the next one."""
        c = self.cutter
        return c.start if c.start is not None else max(c.floor, c.pos - int(PAD_SEC * SR))
