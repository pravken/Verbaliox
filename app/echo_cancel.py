"""
Echo of the speakers in the microphone of a studio recording, removed when the recording is saved.

On a call through speakers the microphone also hears the other people: their voices come once from
the system audio (clean) and once from the microphone (later and duller), and the mix sounds as if
someone talks over them. The system audio is recorded apart (app/system_audio.py), so it is known what
the speakers played: the echo is predicted from it and taken out of the microphone before the mix.

1. Where the echo is: the delay of the system audio in the microphone, measured all through the
   recording (GCC-PHAT on windows where the speakers play); its slow drift between the two sound cards
   and its jumps (a piece of the system sound lost) are followed.
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
from typing import Optional, Tuple

import numpy as np

SR = 24000            # speech up to 12 kHz: the mix sounds as before
BLOCK = 256           # samples per step of the filter
FILTER_SEC = 0.12     # the room's echo tail the filter covers, after the measured delay
MARGIN_SEC = 0.012    # the filter starts a little before the measured delay
MAX_DELAY_SEC = 2.0   # an echo later than this is not looked for (the two tracks can start ~1 s apart)
MIN_ECHO_SCORE = 0.02  # GCC-PHAT peak of a clear echo; without one it stays near 0.006
MAX_WINDOWS = 1500    # windows the delay is measured on, spread over the recording (~1 s of work each 100)
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


def find_echo(mic: np.ndarray, ref: np.ndarray, sr: int = SR, window_sec: float = 4.0) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """The delay of the echo along the recording: (times, lags) in samples, measured on the windows
    where the speakers play, all through the recording (not only its first minutes). The delay drifts
    slowly between two sound cards and can jump when Windows loses a piece of the system sound: each
    window keeps its own measure, a measure unlike its neighbours' is left out. None when the
    microphone does not hear the speakers (headphones)."""
    win = int(window_sec * sr)
    n = min(len(mic), len(ref))
    if n < win:
        return None
    max_lag = int(MAX_DELAY_SEC * sr)
    level = np.sqrt(np.mean(ref[: n // win * win].reshape(-1, win) ** 2, axis=1))
    playing = level[level > 1e-3]
    if not len(playing):
        return None
    floor = max(1e-3, 0.3 * float(np.median(playing)))  # the speakers play there, not a quiet tail
    loud = [int(k) for k in np.nonzero(level > floor)[0]]
    if len(loud) > MAX_WINDOWS:  # spread over the whole recording
        loud = [loud[int(i)] for i in np.linspace(0, len(loud) - 1, MAX_WINDOWS)]
    points = []
    for k in loud:
        lag, score = _gcc_phat(mic[k * win:(k + 1) * win], ref[k * win:(k + 1) * win], max_lag)
        if score >= MIN_ECHO_SCORE:
            points.append((k * win + win / 2, lag))
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
        t = np.arange(a, min(n, a + step), dtype=np.float64)
        src = t - _delay_at(times, lags, t) + margin
        lo = max(0, int(np.floor(src.min())))
        hi = min(len(ref), int(np.ceil(src.max())) + 2)
        if hi - lo < 2:
            continue  # this piece falls outside ref: silence
        out[a:a + len(t)] = np.interp(src, np.arange(lo, hi, dtype=np.float64), ref[lo:hi].astype(np.float64),
                                      left=0.0, right=0.0)
    return out


def _adaptive(mic: np.ndarray, ref: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """(mic without the predicted echo, the predicted echo): partitioned-block frequency-domain NLMS
    that learns only while the speakers play and the microphone holds no other voice."""
    B, n = BLOCK, len(mic)
    P = int(np.ceil(FILTER_SEC * SR / B)) + 1
    blocks = n // B
    W = np.zeros((P, B + 1), dtype=np.complex64)
    X = np.zeros((P, B + 1), dtype=np.complex64)
    power = np.full(B + 1, 1e-6, dtype=np.float32)
    out = np.zeros(n, dtype=np.float32)
    echo = np.zeros(n, dtype=np.float32)
    prev = np.zeros(B, dtype=np.float32)
    ref_peak = np.zeros(P, dtype=np.float32)
    for b in range(blocks):
        s = b * B
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
    tail = blocks * B
    out[tail:] = mic[tail:]
    return out, echo


def _suppress(sig: np.ndarray, echo: np.ndarray) -> np.ndarray:
    """What remains of the echo lowered where the prediction is strong, never below GAIN_FLOOR."""
    n_fft, hop = 512, 256
    win = np.hanning(n_fft + 1)[:-1].astype(np.float32)
    pad = n_fft
    x = np.concatenate([np.zeros(pad, np.float32), sig, np.zeros(pad + n_fft, np.float32)])
    y = np.concatenate([np.zeros(pad, np.float32), echo, np.zeros(pad + n_fft, np.float32)])
    frames = (len(x) - n_fft) // hop
    out = np.zeros(len(x), dtype=np.float32)
    norm = np.zeros(len(x), dtype=np.float32)
    gain = np.ones(n_fft // 2 + 1, dtype=np.float32)
    for f in range(frames):
        s = f * hop
        E = np.fft.rfft(x[s:s + n_fft] * win)
        Y = np.fft.rfft(y[s:s + n_fft] * win)
        g = 1.0 - 1.2 * (np.abs(Y) ** 2) / (np.abs(E) ** 2 + np.abs(Y) ** 2 + 1e-10)
        g = np.clip(g, GAIN_FLOOR, 1.0).astype(np.float32)
        gain = np.maximum(g, 0.6 * gain + 0.4 * g)  # opens at once, closes softly: no musical noise
        out[s:s + n_fft] += np.fft.irfft(E * gain) * win
        norm[s:s + n_fft] += win * win
    out /= np.maximum(norm, 1e-6)
    return out[pad:pad + len(sig)]


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


def clean_microphone(ffmpeg: str, page: Path, system: Path, system_skip: float, out: Path,
                     system_out: Optional[Path] = None) -> bool:
    """Writes the page's microphone without the speakers' echo to `out` (WAV) and, given system_out,
    the system sound lined up with it by the echo (WAV, for the mix). False when there is no echo to
    remove (headphones) or it could not be done: the recording is then mixed as it was."""
    import soundfile as sf

    try:
        mic = _decode(ffmpeg, page)
        ref = _decode(ffmpeg, system, system_skip)
        done = cancel_and_align(mic, ref)
        if done is None:
            print("[echo] the microphone does not hear the speakers: nothing to remove", flush=True)
            return False
        cleaned, in_room = done
        sf.write(str(out), cleaned, SR, subtype="PCM_16")
        if system_out is not None:
            sf.write(str(system_out), np.clip(in_room, -1.0, 1.0), SR, subtype="PCM_16")
        return True
    except Exception as e:  # the recording is saved anyway, with the echo
        print(f"[echo] not removed: {e}", flush=True)
        out.unlink(missing_ok=True)
        if system_out is not None:
            system_out.unlink(missing_ok=True)
        return False
