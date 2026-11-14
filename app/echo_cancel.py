"""
Echo of the speakers in the microphone of a studio recording, removed when the recording is saved.

On a call through speakers the microphone also hears the other people: their voices come once from
the system audio (clean) and once from the microphone (later and duller), and the mix sounds as if
someone talks over them. The system audio is recorded apart (app/system_audio.py), so it is known what
the speakers played: the echo is predicted from it and taken out of the microphone before the mix.

1. Where the echo is: first roughly, by the loudness of the two tracks, up to 90 s apart (they were
   found 24 s apart); then exactly, the delay of the system audio in the microphone measured all
   through the recording (GCC-PHAT on windows where the speakers play) around the rough one; its slow
   drift between the two sound cards and its jumps (a piece of the system sound lost) are followed.
   No clear echo (headphones): nothing is done.
2. An adaptive filter learns how the room changes the sound on its way from the speakers to the
   microphone (partitioned-block frequency-domain NLMS) and subtracts its prediction. It learns only
   while the speakers play and nobody speaks into the microphone (a double-talk check), so the user's
   voice is not taken for echo.
3. What remains of the echo is lowered where the prediction says it is (a gentle spectral gain with a
   floor), never below -16 dB, so the voice keeps its sound.

numpy only; about 20-40 s of work per hour of recording.
"""

import subprocess
from pathlib import Path
from typing import Callable, Optional, Tuple

import numpy as np

SR = 24000            # speech up to 12 kHz: the mix sounds as before
BLOCK = 256           # samples per step of the filter
FILTER_SEC = 0.12     # the room's echo tail the filter covers, after the measured delay
MARGIN_SEC = 0.012    # the filter starts a little before the measured delay
MAX_DELAY_SEC = 2.0   # an echo later than this is not looked for (the two tracks can start ~1 s apart)
MIN_ECHO_SCORE = 0.02  # GCC-PHAT peak of a clear echo; without one it stays near 0.006
MAX_WINDOWS = 1500    # windows the delay is measured on, spread over the recording (~1 s of work each 100)
# Before the fine measure: where the speakers' sound is in the microphone, by the loudness of the two
# (10 ms steps), up to this far apart. The tracks were found 24 s apart: the fine measure, looking
# within MAX_DELAY_SEC only, found no echo, nothing was lined up and every voice came twice
COARSE_MAX_SEC = 90.0
COARSE_WIN_SEC = 60.0
COARSE_STEP_SEC = 20.0
COARSE_MIN_SCORE = 0.35  # correlation of the loudness of a window that found the speakers
FINE_AROUND_SEC = 0.5    # the fine measure then looks this far around the coarse one
MU = 0.35             # step of the filter
GAIN_FLOOR = 0.16     # the residual suppression lowers a bin by 16 dB at most


def _gcc_phat(mic: np.ndarray, ref: np.ndarray, max_lag: int) -> Tuple[int, float]:
    """The lag (samples) at which ref best explains mic, and how clear it is (0..1)."""
    n = 1 << int(np.ceil(np.log2(len(mic) + len(ref))))
    cross = np.fft.rfft(mic, n) * np.conj(np.fft.rfft(ref, n))
    cross /= np.abs(cross) + 1e-12
    cc = np.fft.irfft(cross, n)
    cc = np.concatenate([cc[-max_lag:], cc[: max_lag + 1]])
    i = int(np.argmax(np.abs(cc)))
    return i - max_lag, float(np.abs(cc[i]))


def _envelope(x: np.ndarray, sr: int, rate: int = 100) -> np.ndarray:
    """Loudness in steps of 1/rate s, compressed and without its slow level (speech's syllables stay)."""
    h = sr // rate
    n = len(x) // h
    if n < 2:
        return np.zeros(0, np.float32)
    # in pieces of a minute: the whole recording at once (float64 squares) was 0.7 GB an hour
    e = np.empty(n, dtype=np.float64)
    per = 60 * rate
    for a in range(0, n, per):
        b = min(n, a + per)
        e[a:b] = np.mean(np.asarray(x[a * h: b * h]).reshape(b - a, h).astype(np.float64) ** 2, axis=1)
    e = np.log1p(1000.0 * np.sqrt(e))
    k = 2 * rate  # 2 s
    slow = np.convolve(e, np.ones(k) / k, mode="same")
    return (e - slow).astype(np.float32)


def coarse_lags(mic: np.ndarray, ref: np.ndarray, sr: int = SR, rate: int = 100) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """Where the speakers' sound is in the microphone along the recording, roughly: (times, lags) in
    samples, the microphone `lag` later than the system track. Found by the loudness of 60 s windows
    of the microphone against the system track up to COARSE_MAX_SEC either way. None when the
    microphone does not follow the speakers anywhere."""
    em, er = _envelope(mic, sr, rate), _envelope(ref, sr, rate)
    win, step, max_lag = int(COARSE_WIN_SEC * rate), int(COARSE_STEP_SEC * rate), int(COARSE_MAX_SEC * rate)
    if len(em) < 10 * rate or len(er) < 10 * rate:
        return None
    win = min(win, len(em))
    times, lags = [], []
    for a in range(0, max(1, len(em) - win + 1), step):
        seg = em[a:a + win]
        if float(np.std(seg)) < 1e-3:
            continue
        lo, hi = max(0, a - max_lag), min(len(er), a + win + max_lag)
        part = er[lo:hi]
        if len(part) < win:
            continue
        # normalized cross-correlation of seg against every place in part
        segz = (seg - seg.mean()) / (np.std(seg) * len(seg))
        nfft = 1 << int(np.ceil(np.log2(len(part) + win)))
        num = np.fft.irfft(np.fft.rfft(part, nfft) * np.conj(np.fft.rfft(segz, nfft)), nfft)[: len(part) - win + 1]
        c1 = np.concatenate([[0.0], np.cumsum(part, dtype=np.float64)])
        c2 = np.concatenate([[0.0], np.cumsum(part.astype(np.float64) ** 2)])
        mean = (c1[win:] - c1[:-win]) / win
        std = np.sqrt(np.maximum((c2[win:] - c2[:-win]) / win - mean ** 2, 1e-12))
        ncc = num / std
        j = int(np.argmax(ncc))
        if ncc[j] >= COARSE_MIN_SCORE:
            times.append((a + win / 2) / rate * sr)
            lags.append((a - (lo + j)) / rate * sr)  # the microphone at a heard the system at lo + j
    if len(times) < 2:
        return None
    t, lag = np.array(times), np.array(lags, dtype=float)
    keep = np.ones(len(lag), bool)
    for i in range(len(lag)):  # a window that matched something else
        near = lag[max(0, i - 2): i + 3]
        keep[i] = abs(lag[i] - np.median(near)) <= 0.25 * sr
    t, lag = t[keep], lag[keep]
    return (t, lag) if len(t) >= 2 else None


def find_echo(mic: np.ndarray, ref: np.ndarray, sr: int = SR, window_sec: float = 4.0) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """The delay of the echo along the recording: (times, lags) in samples, measured on the windows
    where the speakers play, all through the recording (not only its first minutes). The delay drifts
    slowly between two sound cards and can jump when Windows loses a piece of the system sound: each
    window keeps its own measure, a measure unlike its neighbours' is left out. None when the
    microphone does not hear the speakers (headphones)."""
    win = int(window_sec * sr)
    n = len(mic)
    if n < win or len(ref) < win:
        return None
    max_lag = int(MAX_DELAY_SEC * sr)
    # Far apart (a piece of the system sound lost or doubled, a late start): the fine measure looks
    # around the coarse one instead of within MAX_DELAY_SEC of the same time
    coarse = coarse_lags(mic, ref, sr) if min(n, len(ref)) > 30 * sr else None
    if coarse is not None and np.max(np.abs(coarse[1])) < 0.8 * max_lag:
        coarse = None  # within the fine measure's own reach: as before
    if coarse is not None:
        print(f"[echo] the tracks are {np.median(coarse[1]) / sr:.1f} s apart (by their loudness, "
              f"{len(coarse[1])} windows)", flush=True)
    reach = int(FINE_AROUND_SEC * sr) if coarse else max_lag
    # each window of the microphone and the part of the system sound it is compared with
    pairs = []
    for k in range(n // win):
        a = k * win
        c = int(round(float(_delay_at(coarse[0], coarse[1], np.array([a + win / 2.0]))[0]))) if coarse else 0
        if 0 <= a - c and a - c + win <= len(ref):
            pairs.append((a, a - c, c))
    if not pairs:
        return None
    level = np.array([np.sqrt(np.mean(ref[r:r + win] ** 2)) for _, r, _ in pairs])
    playing = level[level > 1e-3]
    if not len(playing):
        return None
    floor = max(1e-3, 0.3 * float(np.median(playing)))  # the speakers play there, not a quiet tail
    loud = [i for i in np.nonzero(level > floor)[0]]
    if len(loud) > MAX_WINDOWS:  # spread over the whole recording
        loud = [loud[int(i)] for i in np.linspace(0, len(loud) - 1, MAX_WINDOWS)]
    points = []
    for i in loud:
        a, r, c = pairs[i]
        lag, score = _gcc_phat(mic[a:a + win], ref[r:r + win], reach)
        if score >= MIN_ECHO_SCORE:
            points.append((a + win / 2, c + lag))
    if len(points) < max(2, len(loud) // 4):
        return None
    t = np.array([p[0] for p in points])
    lag = np.array([p[1] for p in points], dtype=float)
    # a window that found something else: far from the median of its neighbours (a jump is followed:
    # after it the neighbours agree with the new delay)
    keep = np.ones(len(lag), bool)
    for i in range(len(lag)):
        near = lag[max(0, i - 3): i + 4]
        keep[i] = abs(lag[i] - np.median(near)) <= 0.02 * sr
    t, lag = t[keep], lag[keep]
    if len(t) < 2:
        return None
    return t, lag


def _delay_at(times: np.ndarray, lags: np.ndarray, at: np.ndarray) -> np.ndarray:
    """The delay at each sample: the measure of the nearest window (a jump stays a jump), and between
    two close measures a straight line (a slow drift stays smooth)."""
    i = np.clip(np.searchsorted(times, at), 1, len(times) - 1)
    t0, t1 = times[i - 1], times[i]
    l0, l1 = lags[i - 1], lags[i]
    w = np.clip((at - t0) / np.maximum(t1 - t0, 1.0), 0.0, 1.0)
    smooth = l0 + (l1 - l0) * w
    step = np.where(at - t0 < t1 - at, l0, l1)
    out = np.where(np.abs(l1 - l0) <= 0.005 * SR, smooth, step)
    out = np.where(at <= times[0], lags[0], out)
    return np.where(at >= times[-1], lags[-1], out)


def _align(ref: np.ndarray, n: int, times: np.ndarray, lags: np.ndarray, margin: int) -> np.ndarray:
    """ref moved so its echo falls at `margin` samples into the filter, following the delay along the
    recording. Done in pieces, each reading only the part of ref it needs: the whole of ref (and a
    float64 grid as long) was converted for every piece, gigabytes for an hour-long recording."""
    out = np.zeros(n, dtype=np.float32)
    step = 4_000_000
    for a in range(0, n, step):
        out[a:min(n, a + step)] = _align_range(ref, a, min(n, a + step), times, lags, margin)
    return out


def _align_range(ref: np.ndarray, a: int, b: int, times: np.ndarray, lags: np.ndarray, margin: int) -> np.ndarray:
    """_align for the samples a..b only."""
    t = np.arange(a, b, dtype=np.float64)
    src = t - _delay_at(times, lags, t) + margin
    lo = max(0, int(np.floor(src.min())))
    hi = min(len(ref), int(np.ceil(src.max())) + 2)
    if hi - lo < 2:
        return np.zeros(b - a, dtype=np.float32)  # this piece falls outside ref: silence
    return np.interp(src, np.arange(lo, hi, dtype=np.float64), np.asarray(ref[lo:hi]).astype(np.float64),
                     left=0.0, right=0.0).astype(np.float32)


class _Adaptive:
    """Partitioned-block frequency-domain NLMS that learns only while the speakers play and the
    microphone holds no other voice; fed piece by piece (whole blocks), its state carried over."""

    def __init__(self) -> None:
        B = BLOCK
        self.P = int(np.ceil(FILTER_SEC * SR / B)) + 1
        self.W = np.zeros((self.P, B + 1), dtype=np.complex64)
        self.X = np.zeros((self.P, B + 1), dtype=np.complex64)
        self.power = np.full(B + 1, 1e-6, dtype=np.float32)
        self.prev = np.zeros(B, dtype=np.float32)
        self.ref_peak = np.zeros(self.P, dtype=np.float32)
        self.b = 0  # blocks done

    def run(self, mic: np.ndarray, ref: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """(mic without the predicted echo, the predicted echo) for len(mic) // BLOCK blocks."""
        B, P = BLOCK, self.P
        blocks = len(mic) // B
        out = np.zeros(blocks * B, dtype=np.float32)
        echo = np.zeros(blocks * B, dtype=np.float32)
        W, X, power, prev, ref_peak = self.W, self.X, self.power, self.prev, self.ref_peak
        for k in range(blocks):
            b = self.b + k
            s = k * B
            cur = ref[s:s + B]
            X = np.roll(X, 1, axis=0)
            X[0] = np.fft.rfft(np.concatenate([prev, cur]))
            prev = cur
            ref_peak = np.roll(ref_peak, 1)
            ref_peak[0] = float(np.max(np.abs(cur))) if cur.size else 0.0
            y = np.fft.irfft((W * X).sum(axis=0))[B:]
            d = mic[s:s + B]
            e = d - y
            out[s:s + B] = e
            echo[s:s + B] = y
            power = 0.9 * power + 0.1 * (np.abs(X[0]) ** 2) / 2
            speakers_play = ref_peak.max() > 1e-3
            # Double talk: the microphone well above what the echo can be (the filter's own estimate and
            # the loudest the speakers played lately) means someone speaks into it: no learning then
            e_pow, y_pow, d_pow = float(np.mean(e * e)), float(np.mean(y * y)), float(np.mean(d * d))
            near_speech = d_pow > 4.0 * y_pow + 1e-7 and b > 40 and y_pow > 1e-9
            if speakers_play and not near_speech:
                E = np.fft.rfft(np.concatenate([np.zeros(B, dtype=np.float32), e]))
                W += (MU * np.conj(X) * E / (power * P + 1e-6)).astype(np.complex64)
                # the filter is kept to one block per partition (gradient constraint, every 4th block)
                if b % 4 == 0:
                    w = np.fft.irfft(W, axis=1)
                    w[:, B:] = 0
                    W = np.fft.rfft(w, axis=1).astype(np.complex64)
            elif e_pow > 4.0 * d_pow and b > 40:
                W *= 0.5  # diverged (the error grew beyond the microphone itself): back off
        self.W, self.X, self.power, self.prev, self.ref_peak = W, X, power, prev, ref_peak
        self.b += blocks
        return out, echo


def _adaptive(mic: np.ndarray, ref: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """(mic without the predicted echo, the predicted echo) of a whole recording."""
    n = len(mic)
    out, echo = _Adaptive().run(mic, ref)
    tail = len(out)
    return np.concatenate([out, np.asarray(mic[tail:], dtype=np.float32)]), np.concatenate([echo, np.zeros(n - tail, np.float32)])


class _Suppressor:
    """What remains of the echo lowered where the prediction is strong, never below GAIN_FLOOR: a short
    STFT fed piece by piece, giving out each sample once no later frame adds to it."""
    N_FFT, HOP = 512, 256

    def __init__(self) -> None:
        self.win = np.hanning(self.N_FFT + 1)[:-1].astype(np.float32)
        self.x = np.zeros(self.N_FFT, np.float32)  # the padding before the signal (as the whole version)
        self.y = np.zeros(self.N_FFT, np.float32)
        self.acc = np.zeros(self.N_FFT, np.float32)
        self.norm = np.zeros(self.N_FFT, np.float32)
        self.gain = np.ones(self.N_FFT // 2 + 1, dtype=np.float32)
        self.skip = self.N_FFT  # samples of the padding still to drop from what is given out

    def feed(self, sig: np.ndarray, echo: np.ndarray) -> np.ndarray:
        n_fft, hop, win = self.N_FFT, self.HOP, self.win
        self.x = np.concatenate([self.x, sig.astype(np.float32, copy=False)])
        self.y = np.concatenate([self.y, echo.astype(np.float32, copy=False)])
        done = []
        pos = 0
        while len(self.x) - pos >= n_fft:
            E = np.fft.rfft(self.x[pos:pos + n_fft] * win)
            Y = np.fft.rfft(self.y[pos:pos + n_fft] * win)
            g = 1.0 - 1.2 * (np.abs(Y) ** 2) / (np.abs(E) ** 2 + np.abs(Y) ** 2 + 1e-10)
            g = np.clip(g, GAIN_FLOOR, 1.0).astype(np.float32)
            self.gain = np.maximum(g, 0.6 * self.gain + 0.4 * g)  # opens at once, closes softly: no musical noise
            self.acc += (np.fft.irfft(E * self.gain) * win).astype(np.float32)
            self.norm += win * win
            done.append(self.acc[:hop] / np.maximum(self.norm[:hop], 1e-6))  # no later frame reaches these
            self.acc = np.concatenate([self.acc[hop:], np.zeros(hop, np.float32)])
            self.norm = np.concatenate([self.norm[hop:], np.zeros(hop, np.float32)])
            pos += hop
        self.x, self.y = self.x[pos:], self.y[pos:]
        out = np.concatenate(done) if done else np.zeros(0, np.float32)
        if self.skip:
            cut = min(self.skip, len(out))
            out, self.skip = out[cut:], self.skip - cut
        return out

    def finish(self, total: int, given: int) -> np.ndarray:
        """The rest, up to `total` samples given out in all (`given` so far)."""
        out = self.feed(np.zeros(2 * self.N_FFT, np.float32), np.zeros(2 * self.N_FFT, np.float32))
        return out[: max(0, total - given)]


def _suppress(sig: np.ndarray, echo: np.ndarray) -> np.ndarray:
    """What remains of the echo lowered where the prediction is strong, never below GAIN_FLOOR."""
    sp = _Suppressor()
    head = sp.feed(sig, echo)
    return np.concatenate([head, sp.finish(len(sig), len(head))])[: len(sig)]


def cancel_and_align(mic: np.ndarray, ref: np.ndarray, sr: int = SR) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """(the microphone without the echo of the speakers, the system sound moved to where the
    microphone heard it), or None when the microphone does not hear the speakers. The second is what
    the mix uses: the time the page and the app say their tracks began can be off by most of a second,
    and then whatever echo is left sounds like a second voice; where the microphone heard the speakers
    is measured in the sound itself."""
    found = find_echo(mic, ref, sr)
    if not found:
        return None
    times, lags = found
    jumps = int(np.sum(np.abs(np.diff(lags)) > 0.005 * sr))
    print(f"[echo] delay {lags[0] / sr:.3f}..{lags[-1] / sr:.3f} s over {len(lags)} windows, jumps: {jumps}", flush=True)
    margin = int(MARGIN_SEC * sr)
    aligned = _align(ref, len(mic), times, lags, margin)
    cleaned, echo = _adaptive(mic.astype(np.float32, copy=False), aligned)
    del aligned
    in_room = _align(ref, len(mic), times, lags, 0)
    return np.clip(_suppress(cleaned, echo), -1.0, 1.0), in_room


def cancel(mic: np.ndarray, ref: np.ndarray, sr: int = SR) -> Optional[np.ndarray]:
    """The microphone without the echo of the speakers, or None when it does not hear them."""
    done = cancel_and_align(mic, ref, sr)
    return done[0] if done else None


def _decode(ffmpeg: str, path: Path, skip: float = 0.0) -> np.ndarray:
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", *(["-ss", f"{skip:.3f}"] if skip >= 0.02 else []),
           "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    res = subprocess.run(cmd, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if res.returncode != 0:
        raise RuntimeError((res.stderr or b"").decode("utf-8", "replace")[-300:])
    return np.frombuffer(res.stdout, dtype=np.float32)


def _decode_to_disk(ffmpeg: str, path: Path, raw: Path, skip: float = 0.0) -> np.ndarray:
    """The track as float32 samples in a file on disk, read through a memory map: an hour is 345 MB a
    track, and the two tracks with what was made of them held 2.5–3 GB of memory at once."""
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *(["-ss", f"{skip:.3f}"] if skip >= 0.02 else []),
           "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", str(raw)]
    res = subprocess.run(cmd, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if res.returncode != 0 or not raw.is_file():
        raise RuntimeError((res.stderr or b"").decode("utf-8", "replace")[-300:])
    if raw.stat().st_size < 4:
        return np.zeros(0, dtype=np.float32)
    return np.memmap(raw, dtype=np.float32, mode="r")


CHUNK_SEC = 60  # what is worked on at a time: memory stays the same (~150 MB) for an hour or for eight


def clean_microphone(ffmpeg: str, page: Path, system: Path, system_skip: float, out: Path,
                     system_out: Optional[Path] = None, progress: Optional[Callable[[float], None]] = None) -> bool:
    """Writes the page's microphone without the speakers' echo to `out` (WAV) and, given system_out,
    the system sound lined up with it by the echo (WAV, for the mix). False when there is no echo to
    remove (headphones) or it could not be done: the recording is then mixed as it was. Worked through
    in pieces of CHUNK_SEC, the filter carried from one to the next (the result is the same as at once);
    `progress(0..1)` says how far."""
    import shutil
    import tempfile

    import soundfile as sf

    tmp = Path(tempfile.mkdtemp(prefix=".echo_", dir=str(out.parent)))
    mic = ref = None
    try:
        mic = _decode_to_disk(ffmpeg, page, tmp / "mic.f32")
        ref = _decode_to_disk(ffmpeg, system, tmp / "sys.f32", system_skip)
        n = len(mic)
        print(f"[echo] microphone {n / SR:.1f} s, system sound {len(ref) / SR:.1f} s "
              f"(after {system_skip:.2f} s skipped)", flush=True)
        found = find_echo(mic, ref, SR)
        if not found:
            print("[echo] the microphone does not hear the speakers: nothing to remove", flush=True)
            return False
        times, lags = found
        jumps = int(np.sum(np.abs(np.diff(lags)) > 0.005 * SR))
        print(f"[echo] delay {lags[0] / SR:.3f}..{lags[-1] / SR:.3f} s over {len(lags)} windows, jumps: {jumps}", flush=True)
        margin = int(MARGIN_SEC * SR)
        chunk = max(BLOCK, int(CHUNK_SEC * SR) // BLOCK * BLOCK)
        adaptive, suppressor, given = _Adaptive(), _Suppressor(), 0
        with sf.SoundFile(str(out), "w", samplerate=SR, channels=1, subtype="PCM_16") as fo, \
                (sf.SoundFile(str(system_out), "w", samplerate=SR, channels=1, subtype="PCM_16")
                 if system_out is not None else _NoFile()) as fs:
            for a in range(0, n, chunk):
                b = min(n, a + chunk)
                m = np.asarray(mic[a:b], dtype=np.float32)
                cleaned, echo = adaptive.run(m, _align_range(ref, a, b, times, lags, margin))
                if len(cleaned) < len(m):  # the end of the recording: less than a block, as it was
                    cleaned = np.concatenate([cleaned, m[len(cleaned):]])
                    echo = np.concatenate([echo, np.zeros(len(m) - len(echo), np.float32)])
                done = suppressor.feed(cleaned, echo)
                fo.write(np.clip(done, -1.0, 1.0))
                given += len(done)
                fs.write(np.clip(_align_range(ref, a, b, times, lags, 0), -1.0, 1.0))
                if progress:
                    progress(b / max(1, n))
            fo.write(np.clip(suppressor.finish(n, given), -1.0, 1.0))
        return True
    except Exception as e:  # the recording is saved anyway, with the echo
        print(f"[echo] not removed: {e}", flush=True)
        out.unlink(missing_ok=True)
        if system_out is not None:
            system_out.unlink(missing_ok=True)
        return False
    finally:
        del mic, ref  # the memory maps let go of their files before they are deleted (Windows)
        shutil.rmtree(tmp, ignore_errors=True)


class _NoFile:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def write(self, _data) -> None:
        pass
