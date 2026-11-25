"""
Live captions by VAD phrases (bench-report/asr-2026-11.md, item 3): for Russian with GigaAM v3 e2e-CTC int8.

Instead of recognizing a sliding window of up to 20 s again and again (app/live.py), the Silero VAD follows the
stream frame by frame (32 ms) and only the phrase being spoken is recognized: from the start of speech, as a
draft every DRAFT_MIN_SEC or more (DraftPace: never sooner than three times the last draft took), and once more
as the final text after a pause of END_PAUSE_SEC. In the bench this
gave the final text in 0.9–1.1 s instead of 3–4 s, with a lower WER, a seventh of the processor load and 0.44 GB of
memory instead of 2.9.

Speech without pauses is cut at MAX_PHRASE_SEC, in a gap between words: a frame the VAD hears below KEEP_PROB,
the weakest of the last CUT_SEARCH_SEC, else the latest of the second half of the phrase; only without any such frame
where the speech is weakest in the last CUT_SEARCH_SEC (a breath). The next phrase starts exactly there: no audio
is recognized twice and none is left out (the duplicated and lost words at forced cuts of other programs,
Meetily issue #756). A word cut in half all the same is heard by both phrases (bench-report/asr-2026-11-check.md:
«которых ко которых», «и и вправду»): at the seam the next phrase loses its first word when it repeats the last one
of the phrase before or is the start of it (drop_seam_repeat), and a tail of the cut shorter than MIN_SPEECH_SEC or
of one letter is not a line of its own (tail_fragment).

The stream is levelled as the recordings are (app.asr_onnx.level), from the loudest part of the last 10 s:
quiet speech is otherwise taken for silence by the VAD.
"""

from collections import deque
from pathlib import Path
from time import perf_counter as _clock
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
TAIL_FRAGMENT_SEC = 1.0  # a phrase after a forced cut this short with one letter is a fragment, no line
PAD_SEC = 0.1          # audio kept before the speech starts and after it ends
DRAFT_MIN_SEC = 0.3    # a draft of the phrase being spoken at most this often (on average, in audio received)
DRAFT_COST_SHARE = 3.0  # and at most every this many times its own recognition time (DraftPace)
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
            if end <= start:  # cut in a gap that went on into the pause: nothing is left of the phrase
                self.floor = start
                return None
            self.floor = end
            return start, end, False
        if self.pos - self.start >= MAX_PHRASE_SEC * SR:
            cut = self._cut_point()
            start, self.start, self.floor, self.continued = self.start, cut, cut, True
            self.probs = [(s, q) for s, q in self.probs if s >= cut]
            return start, cut, True
        return None

    def _cut_point(self) -> int:
        """Where speech without a pause is cut, in the middle of a frame: the weakest frame below KEEP_PROB (a gap
        between words) in the last CUT_SEARCH_SEC, the latest one of equals (the cut phrase keeps as much as it
        can); else the latest such frame in the second half of the phrase; only without any, the weakest frame of
        the last CUT_SEARCH_SEC (a word may be cut in half there)."""
        half = self.start + int(MAX_PHRASE_SEC * SR / 2)
        recent = max(half, self.pos - int(CUT_SEARCH_SEC * SR))
        gaps = [(q, -s, s) for s, q in self.probs if s >= recent and q < KEEP_PROB]
        if not gaps:
            earlier = [s for s, q in self.probs if s >= half and q < KEEP_PROB]
            if earlier:
                return min(self.pos, earlier[-1] + FRAME // 2)
            gaps = [(q, -s, s) for s, q in self.probs if s >= recent]
        if not gaps:
            return self.pos
        _, _, s = min(gaps)
        return min(self.pos, s + FRAME // 2)


def _word(w: str) -> str:
    return "".join(ch for ch in w.lower().replace("ё", "е") if ch.isalnum())


def last_word(text: str) -> str:
    """The last word of a line as drop_seam_repeat compares it ("" for none)."""
    words = [_word(w) for w in text.split()]
    words = [w for w in words if w]
    return words[-1] if words else ""


def drop_seam_repeat(prev_last: str, text: str, most: int = 2) -> str:
    """The text of the phrase after a forced cut without the word cut in half heard twice: its first words while
    they repeat the last word of the phrase before (any case and punctuation: «и» | «и вправду») or are the start
    of it («которых» | «ко которых»), at most `most` of them."""
    prev = _word(prev_last)
    if not prev:
        return text
    words = text.split()
    dropped = 0
    while words and dropped < most:
        w = _word(words[0])
        if not w or not (w == prev or len(w) >= 2 and prev.startswith(w)):
            break
        words.pop(0)
        dropped += 1
    return " ".join(words) if dropped else text


def tail_fragment(samples: int, text: str) -> bool:
    """The phrase after a forced cut is only its tail: shorter than MIN_SPEECH_SEC, or shorter than
    TAIL_FRAGMENT_SEC with one letter or digit at most (a line of one character from a phrase of 0.04 s in
    bench-report/asr-2026-11-check.md)."""
    if samples < MIN_SPEECH_SEC * SR:
        return True
    return samples < TAIL_FRAGMENT_SEC * SR and sum(ch.isalnum() for ch in text) <= 1


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


class DraftPace:
    """How often the draft of the phrase being spoken is recognized again: every DRAFT_MIN_SEC of audio received, but
    never sooner than DRAFT_COST_SHARE times the time the last draft took, so drafts take at most a third of the
    caption copy's threads and a slow computer gets fewer drafts instead of a backlog. The schedule runs on audio
    received: the page sends it in pieces of about 0.25 s, so the drafts fall on every first or second piece and
    keep the interval on average; after a delay (the model busy with a final or a window) one draft is made and the
    schedule starts again from there, with no burst of drafts to catch up."""

    def __init__(self) -> None:
        self.cost = 0.0           # seconds the last draft took
        self.next_at: Optional[float] = None  # audio received (s) from which the next draft is due; None: at once

    def interval(self) -> float:
        return max(DRAFT_MIN_SEC, DRAFT_COST_SHARE * self.cost)

    def due(self, received: float) -> bool:
        return self.next_at is None or received >= self.next_at - 1e-6

    def done(self, received: float, cost: float) -> None:
        """A draft was recognized at `received` seconds of audio and took `cost` seconds."""
        self.cost = max(0.0, cost)
        step = self.interval()
        planned = received if self.next_at is None else self.next_at
        # on schedule: from the planned time (the average holds); late: no sooner than half an interval from now
        self.next_at = max(planned + step, received + step / 2)

    def restart(self) -> None:
        """A phrase ended: the first draft of the next one is due as soon as it has MIN_DRAFT_SEC of speech."""
        self.next_at = None

    def run(self, received: float, recognize: Any) -> Any:
        """`recognize()` timed: its result, and the schedule moved on."""
        t = _clock()
        try:
            return recognize()
        finally:
            self.done(received, _clock() - t)


class PhraseState:
    """What a caption session keeps between steps in this mode."""

    def __init__(self, start_at: int, vad: Any):
        self.cutter = PhraseCutter(start_at)
        self.vad = vad
        self.level = StreamLevel()
        self.levelled_to = start_at  # the stream is levelled in place up to here
        self.pace = DraftPace()      # when the draft of the phrase being spoken is recognized again
        self.drafted_to = start_at   # and up to where the last draft heard it (in a pause no new draft)
        self.after_cut = False       # the phrase before was ended by a forced cut
        self.seam = ""               # and this was its last word

    def keep_from(self) -> int:
        """The first sample still needed: the start of the phrase going on, or a little before the next one."""
        c = self.cutter
        return c.start if c.start is not None else max(c.floor, c.pos - int(PAD_SEC * SR))
