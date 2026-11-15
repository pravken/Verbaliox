import inspect
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import soundfile as sf
import torch
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import silhouette_score
from sklearn.metrics.pairwise import cosine_distances

from app.database import MODELS_DIR
from app.hardware import clear_vram

SPEAKER_COLORS = [
    "#6366f1",  # Indigo
    "#10b981",  # Emerald
    "#f59e0b",  # Amber
    "#ec4899",  # Pink
    "#06b6d4",  # Cyan
    "#8b5cf6",  # Violet
    "#ef4444",  # Red
    "#14b8a6",  # Teal
]

# Auto mode: minimum anchor speech for a cluster to count as a separate speaker
MIN_SPEAKER_SECONDS = 4.0
MIN_SPEAKER_SHARE = 0.03
MAX_MIN_SPEAKER_SECONDS = 20.0
SCRAPS_FROM_SECONDS = 120.0  # Nemotron's tiny groups are set aside only in recordings this long or longer

_ecapa_model = None
_ecapa_device = None


def _ensure_hf_compat() -> None:
    """
    Ensures compatibility between SpeechBrain and newer huggingface_hub / torchaudio versions.
    """
    import huggingface_hub

    orig_download = huggingface_hub.hf_hub_download
    sig = inspect.signature(orig_download)
    if "use_auth_token" not in sig.parameters:
        def _patched_hf_hub_download(*args, **kwargs):
            if "use_auth_token" in kwargs:
                val = kwargs.pop("use_auth_token")
                if val and "token" not in kwargs:
                    kwargs["token"] = val
            return orig_download(*args, **kwargs)

        huggingface_hub.hf_hub_download = _patched_hf_hub_download


def _get_ecapa_encoder(device: str = "cpu"):
    global _ecapa_model, _ecapa_device
    from app.hardware import torch_cuda_works

    # A card PyTorch has no kernels for (an RTX 50 for this CUDA 12.6 build): the processor
    target_device = "cuda:0" if (device.startswith("cuda") and torch_cuda_works()) else "cpu"

    if _ecapa_model is not None and _ecapa_device == target_device:
        return _ecapa_model

    _ensure_hf_compat()
    from speechbrain.inference.speaker import EncoderClassifier
    from speechbrain.utils.fetching import LocalStrategy

    save_dir = MODELS_DIR / "spkrec-ecapa-voxceleb"
    save_dir.mkdir(parents=True, exist_ok=True)

    from huggingface_hub import snapshot_download

    from app.model_manager import ECAPA_REPO, ECAPA_REVISION

    # from_hparams has no revision: the fixed commit is fetched into the folder and the model is loaded
    # from the folder. Only when it is not there: the check itself asked huggingface.co at every job
    from app.model_manager import is_diarizer_installed

    if not is_diarizer_installed():
        snapshot_download(ECAPA_REPO, revision=ECAPA_REVISION, local_dir=str(save_dir))
    _ecapa_model = EncoderClassifier.from_hparams(
        source=str(save_dir),
        savedir=str(save_dir),
        run_opts={"device": target_device},
        local_strategy=LocalStrategy.COPY,
    )
    _ecapa_device = target_device
    return _ecapa_model


def ecapa_loaded_on() -> Optional[str]:
    """Device of the cached speaker-embedding model, or None when it is not loaded."""
    return _ecapa_device if _ecapa_model is not None else None


def unload_diarizer() -> None:
    global _ecapa_model, _ecapa_device
    _ecapa_model = None
    _ecapa_device = None
    clear_vram()


def _split_segments_by_word_pauses(
    raw_segments: List[Dict[str, Any]],
    pause_threshold: float = 0.48,
    max_chunk_duration: float = 12.0,
) -> List[Dict[str, Any]]:
    """
    Splits long Whisper segments at natural pauses between words (> 0.48s) or sentence
    endings so speaker changes inside a segment are captured accurately.
    """
    refined: List[Dict[str, Any]] = []

    for seg in raw_segments:
        words = seg.get("words") or []
        # keep_whole: a line typed over (app/transcriber.resplit_input), its text is not its words
        if not words or len(words) <= 2 or seg.get("keep_whole"):
            refined.append(seg)
            continue
        # what else the line holds (its language) goes with each of its pieces
        extra = {k: v for k, v in seg.items() if k not in ("start", "end", "text", "words", "id", "speaker")}

        current_words = [words[0]]
        for prev_w, curr_w in zip(words[:-1], words[1:]):
            gap = float(curr_w["start"]) - float(prev_w["end"])
            chunk_dur = float(prev_w["end"]) - float(current_words[0]["start"])
            ends_sentence = str(prev_w.get("word", "")).strip().endswith((".", "?", "!"))

            if (gap >= pause_threshold and chunk_dur >= 1.0) or (
                ends_sentence and gap >= 0.22 and chunk_dur >= 2.2
            ) or (chunk_dur >= max_chunk_duration and ends_sentence):
                text = "".join(w["word"] for w in current_words).strip()
                if text:
                    refined.append(
                        {
                            **extra,
                            "start": round(float(current_words[0]["start"]), 2),
                            "end": round(float(current_words[-1]["end"]), 2),
                            "text": text,
                            "words": current_words,
                        }
                    )
                current_words = [curr_w]
            else:
                current_words.append(curr_w)

        if current_words:
            text = "".join(w["word"] for w in current_words).strip()
            if text:
                refined.append(
                    {
                        **extra,
                        "start": round(float(current_words[0]["start"]), 2),
                        "end": round(float(current_words[-1]["end"]), 2),
                        "text": text,
                        "words": current_words,
                    }
                )

    return refined


def _prepare_slice(
    audio_data: np.ndarray,
    sr: int,
    start_sec: float,
    end_sec: float,
) -> Optional[np.ndarray]:
    """
    Cuts the 16 kHz waveform for one segment, padded with context when short (< 2.2 s) for a
    more stable voiceprint and capped to 10 s around the centre. Returns None for slices that are
    too short or silent to embed.
    """
    total_samples = len(audio_data)
    dur = end_sec - start_sec
    if dur < 0.35:
        return None

    pad = max(0.0, (2.2 - dur) / 2.0)
    s_idx = max(0, int((start_sec - pad) * sr))
    e_idx = min(total_samples, int((end_sec + pad) * sr))
    if (e_idx - s_idx) > 10 * sr:
        mid = (s_idx + e_idx) // 2
        s_idx = mid - 5 * sr
        e_idx = mid + 5 * sr

    chunk = audio_data[s_idx:e_idx]
    if len(chunk) < int(0.35 * sr):
        return None

    # Check RMS energy to avoid embedding pure silence
    rms = float(np.sqrt(np.mean(chunk**2)))
    if rms < 1e-4:
        return None
    return chunk


# Up to this many samples (items x longest item) go through the encoder at once:
# 32 slices of 10 s = 5.1 M samples, a few hundred MB of activations.
_EMBED_BATCH_SAMPLES = 32 * 10 * 16000
_EMBED_BATCH_MAX_ITEMS = 64


def _embed_slices(
    encoder,
    chunks: List[np.ndarray],
    progress: Optional[Callable[[int, int], None]] = None,
) -> List[np.ndarray]:
    """
    Computes L2-normalised 192-dim ECAPA embeddings for many slices in padded batches.
    Slices are sorted by length so a batch holds similar lengths (little padding); the relative
    lengths are passed to the encoder so padding does not affect normalisation or pooling.
    """
    order = sorted(range(len(chunks)), key=lambda i: len(chunks[i]))
    out: List[Optional[np.ndarray]] = [None] * len(chunks)
    pos = 0
    while pos < len(order):
        batch = [order[pos]]
        while pos + len(batch) < len(order) and len(batch) < _EMBED_BATCH_MAX_ITEMS:
            nxt = order[pos + len(batch)]
            if len(chunks[nxt]) * (len(batch) + 1) > _EMBED_BATCH_SAMPLES:
                break
            batch.append(nxt)
        max_len = max(len(chunks[i]) for i in batch)
        wavs = np.zeros((len(batch), max_len), dtype=np.float32)
        for row, i in enumerate(batch):
            wavs[row, : len(chunks[i])] = chunks[i]
        wav_lens = torch.tensor([len(chunks[i]) / max_len for i in batch], dtype=torch.float32)
        with torch.no_grad():
            embs = encoder.encode_batch(torch.from_numpy(wavs), wav_lens)
        vecs = embs.reshape(len(batch), -1).cpu().numpy().astype(np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        vecs = vecs / np.where(norms > 1e-8, norms, 1.0)
        for row, i in enumerate(batch):
            out[i] = vecs[row]
        pos += len(batch)
        if progress:
            progress(pos, len(order))
    return out  # type: ignore[return-value]


OVERRIDE_MIN_SPEAKERS = 3   # a count of 1 or 2 said is corrected only to three voices or more
OVERRIDE_MIN_SCORE = 0.30   # and only when the groups are clearly apart (silhouette of the voices)


SAME_VOICE_CENTROIDS = 0.32  # centroids closer than this (cosine distance) are one voice in Auto mode


def _group_voices(embs: np.ndarray, durs: np.ndarray, k: int, min_dur: float, rounds: int = 6) -> Optional[np.ndarray]:
    """Average-linkage grouping into k voices. A group too small to be a person (one phrase, or less
    speech than min_dur) is set aside (-1) and the rest grouped again. None: no k real groups."""
    active = np.ones(len(embs), dtype=bool)
    for _ in range(rounds):
        if int(active.sum()) <= k:
            return None
        idx = np.flatnonzero(active)
        lab = AgglomerativeClustering(n_clusters=k, metric="cosine", linkage="average").fit_predict(embs[active])
        small = [c for c in range(k) if int(np.sum(lab == c)) < 2 or float(np.sum(durs[idx[lab == c]])) < min_dur]
        if not small:
            labels = np.full(len(embs), -1)
            labels[idx] = lab
            return labels
        for c in small:
            active[idx[lab == c]] = False
    return None


def _turn_speaker(start: float, end: float, turns: List[Tuple[float, float, int]], min_share: float = 0.3) -> Optional[int]:
    """The speaker of Nemotron's turns (start, end, speaker) who covers most of start..end, if they cover
    at least `min_share` of it; None when the span is mostly unmarked (Nemotron leaves short or quiet
    speech out: 23 % of the speech on AMI)."""
    span = max(end - start, 0.05)
    covered: Dict[int, float] = {}
    for t0, t1, spk in turns:
        if t1 <= start or t0 >= end:
            continue
        covered[spk] = covered.get(spk, 0.0) + min(t1, end) - max(t0, start)
    if not covered:
        return None
    spk, sec = max(covered.items(), key=lambda kv: kv[1])
    return spk if sec >= min_share * span else None


# A piece cut off at a change of speaker shorter than this stays with its neighbour: with overlapping
# speech a phrase was cut into one- and two-word scraps between people (AMI EN2002b: 151 phrases became
# 426, 146 of them of 1-2 words; a Russian interview's question split mid-name). A short answer of its
# own («да», «угу», «okay») is still cut out: that is who said it.
MIN_PIECE_SEC = 1.0
MIN_PIECE_WORDS = 3
_BACKCHANNEL = re.compile(
    r"^(да|ага|угу|ну|нет|ок|окей|хорошо|понял[аи]?|ясно|верно|точно|конечно|согласен|согласна|спасибо|"
    r"yes|yeah|yep|no|nope|ok|okay|right|sure|exactly|mhm|uh-huh|thanks|good|great)$", re.I)


def _is_backchannel(words: List[Dict[str, Any]]) -> bool:
    tokens = [re.sub(r"[^\w-]+", "", str(w.get("word") or "")).lower() for w in words]
    tokens = [t for t in tokens if t]
    return 0 < len(tokens) <= 3 and all(_BACKCHANNEL.match(t) for t in tokens)


def _split_by_turns(segments: List[Dict[str, Any]], turns: List[Tuple[float, float, int]]) -> List[Dict[str, Any]]:
    """A phrase whose words Nemotron gives to two people is cut where the speaker changes (a quick
    «да» of another person inside someone's phrase); a word nobody covers stays with the one before,
    and a piece too short to be a turn of its own stays with its neighbour."""
    out: List[Dict[str, Any]] = []
    for seg in segments:
        words = seg.get("words") or []
        if len(words) < 2 or seg.get("keep_whole"):
            out.append(seg)
            continue
        owners: List[Optional[int]] = [_turn_speaker(float(w["start"]), float(w["end"]), turns, 0.01) for w in words]
        last = next((o for o in owners if o is not None), None)
        for i, o in enumerate(owners):
            owners[i] = last = (o if o is not None else last)
        runs: List[List[Any]] = []  # [owner, words]
        for w, o in zip(words, owners):
            if runs and runs[-1][0] == o:
                runs[-1][1].append(w)
            else:
                runs.append([o, [w]])
        changed = True
        while changed and len(runs) > 1:
            changed = False
            for i, (o, ws) in enumerate(runs):
                dur = float(ws[-1]["end"]) - float(ws[0]["start"])
                if (dur >= MIN_PIECE_SEC and len(ws) >= MIN_PIECE_WORDS) or _is_backchannel(ws):
                    continue
                j = i - 1 if i > 0 else i + 1  # into the piece before it (the first: into the next)
                if j < i:
                    runs[j][1].extend(ws)
                else:
                    runs[j][1][:0] = ws
                del runs[i]
                merged: List[List[Any]] = []
                for r in runs:  # neighbours of one speaker again: one piece
                    if merged and merged[-1][0] == r[0]:
                        merged[-1][1].extend(r[1])
                    else:
                        merged.append(r)
                runs = merged
                changed = True
                break
        if len(runs) == 1:
            out.append(seg)
            continue
        extra = {k: v for k, v in seg.items() if k not in ("start", "end", "text", "words", "id", "speaker")}
        out.extend(_words_piece(extra, ws) for _, ws in runs)
    return [p for p in out if str(p.get("text") or "").strip() or not p.get("words")]


def _words_piece(extra: Dict[str, Any], words: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {**extra, "start": round(float(words[0]["start"]), 2), "end": round(float(words[-1]["end"]), 2),
            "text": "".join(w["word"] for w in words).strip(), "words": words}


def _labels_from_turns(
    segments: List[Dict[str, Any]],
    valid_indices: List[int],
    embeddings: Optional[np.ndarray],
    durations: np.ndarray,
    turns: List[Tuple[float, float, int]],
    num_speakers_hint: int = 0,
) -> List[int]:
    """A speaker for every phrase from Nemotron's turns. A phrase it left unmarked goes to the closest
    voice (ECAPA, the centroid of the phrases it did mark for each person), or to the phrase next to it
    when it has no voice print either. A count said is the most there are: the people heard least are
    taken apart as with ECAPA (_fold_least_heard). Numbered in the order they first speak."""
    n = len(segments)
    by_turn: List[Optional[int]] = [_turn_speaker(float(s["start"]), float(s["end"]), turns) for s in segments]
    pos_of = {seg_idx: pos for pos, seg_idx in enumerate(valid_indices)}
    if embeddings is not None and len(embeddings):
        known = [(pos_of[i], by_turn[i]) for i in range(n) if i in pos_of and by_turn[i] is not None]
        spks = sorted({spk for _, spk in known})
        if spks:
            cents = []
            for spk in spks:
                rows = [p for p, sp in known if sp == spk]
                w = np.clip(durations[rows], 0.5, 10.0)[:, None]
                c = np.sum(embeddings[rows] * w, axis=0)
                cents.append(c / max(float(np.linalg.norm(c)), 1e-8))
            cents_arr = np.vstack(cents)
            for i in range(n):
                if by_turn[i] is None and i in pos_of:
                    by_turn[i] = spks[int(np.argmax(cents_arr @ embeddings[pos_of[i]]))]
    marked = [i for i in range(n) if by_turn[i] is not None]
    if not marked:
        return [0] * n
    for i in range(n):  # no voice print and no turn: the speaker of the closest marked phrase
        if by_turn[i] is None:
            by_turn[i] = by_turn[min(marked, key=lambda m: abs(m - i))]
    labels = np.array(by_turn, dtype=int)
    keep = _groups_to_keep(labels[np.array(valid_indices, dtype=int)] if len(valid_indices) else labels[:0],
                           durations, num_speakers_hint)
    if keep and len(set(labels.tolist())) > keep and embeddings is not None and len(valid_indices):
        rows = np.array(valid_indices)
        # each phrase of a group taken apart goes to its closest voice (they were all put on the voice of
        # the group's first phrase before: found by an audit); the groups kept keep their numbers
        labels[rows] = _fold_least_heard(embeddings, durations, labels[rows], keep, renumber=False)
        kept = set(labels[rows].tolist())
        sure = [i for i in range(n) if int(labels[i]) in kept]
        for i in range(n):  # a phrase without a voice print of a group taken apart: its closest neighbour's
            if int(labels[i]) not in kept and sure:
                labels[i] = labels[min(sure, key=lambda j: abs(j - i))]
    order: Dict[int, int] = {}
    out = []
    for v in labels.tolist():
        order.setdefault(int(v), len(order))
        out.append(order[int(v)])
    return out


def _groups_to_keep(labels: np.ndarray, durations: np.ndarray, num_speakers_hint: int = 0) -> int:
    """How many of Nemotron's groups are people: a group heard less than ECAPA's least person (4 s, 3 % of
    the speech, at most 20 s) is a scrap — a laugh, a cough, one voice split off. On a 44-minute talk of
    two Nemotron found five in Auto, two of them 12-15 s (the PC check of 0.8.7-beta.2). A count said
    is the most there are."""
    groups = sorted(set(labels.tolist()))
    total = float(np.sum(durations)) if len(durations) == len(labels) else 0.0
    if len(groups) < 2 or total < SCRAPS_FROM_SECONDS:  # a short recording: a few seconds may be a person
        return min(len(groups), num_speakers_hint) if num_speakers_hint > 1 else len(groups)
    least = min(MAX_MIN_SPEAKER_SECONDS, max(MIN_SPEAKER_SECONDS, MIN_SPEAKER_SHARE * total))
    people = sum(1 for g in groups if float(np.sum(durations[labels == g])) >= least)
    keep = max(1, people)
    if num_speakers_hint > 1:
        keep = max(min(keep, num_speakers_hint), min(2, num_speakers_hint, len(groups)))
    return keep


def _fold_least_heard(embeddings: np.ndarray, durations: np.ndarray, labels: np.ndarray, k: int,
                      renumber: bool = True) -> np.ndarray:
    """Fewer groups than Auto found, as many as said: the group heard least is taken apart, each of its
    phrases going to the closest remaining voice (duration-weighted centroids), until k are left;
    renumbered in the order they first speak. The extra group Auto finds is a small one (scraps of
    speech, a laugh, one person's other microphone): joined whole to its closest group instead, two
    real people were put together (AMI with 4 said: 11-26 % of the time to the wrong person against
    3-7 % in Auto, bench-report/diarization.md, 2026-11-15)."""
    labels = labels.copy()

    def centroid(g: int) -> np.ndarray:
        mask = labels == g
        w = np.clip(durations[mask], 0.5, 10.0)[:, None]
        c = np.sum(embeddings[mask] * w, axis=0)
        n = np.linalg.norm(c)
        return c / (n if n > 1e-8 else 1.0)

    while len(set(labels.tolist())) > k:
        groups = sorted(set(labels.tolist()))
        heard = {g: float(np.sum(durations[labels == g])) for g in groups}
        least = min(groups, key=lambda g: heard[g])
        rest = [g for g in groups if g != least]
        cents = np.vstack([centroid(g) for g in rest])
        idx = np.where(labels == least)[0]
        nearest = np.argmax(embeddings[idx] @ cents.T, axis=1)
        labels[idx] = np.array(rest)[nearest]
    if not renumber:  # the groups keep their own numbers (the ones taken apart are gone)
        return labels
    order: Dict[int, int] = {}
    out = np.zeros(len(labels), dtype=int)
    for i, lbl in enumerate(labels):
        g = int(lbl)
        if g not in order:
            order[g] = len(order)
        out[i] = order[g]
    return out


def _determine_clusters(
    embeddings: np.ndarray,
    durations: np.ndarray,
    num_speakers_hint: int = 0,
    max_speakers: int = 8,
) -> np.ndarray:
    """
    Clusters L2-normalized speaker embeddings using Cosine Agglomerative Clustering.
    Automatically detects if only 1 speaker is present or picks optimal K via Silhouette Score,
    duration-weighted centroids, and inter-centroid cosine distance verification.
    """
    n_samples = len(embeddings)
    if n_samples == 0:
        return np.array([], dtype=int)
    # One or two speakers said for the recording, but the voices clearly make three or more: the count
    # is corrected (a wrong hint put a whole meeting into one or two speakers)
    if num_speakers_hint in (1, 2) and n_samples >= 8:
        auto = _determine_clusters(embeddings, durations, 0, max_speakers)
        found = len(set(auto.tolist()))
        if found >= OVERRIDE_MIN_SPEAKERS:
            mask = durations >= 1.4
            try:
                score = float(silhouette_score(embeddings[mask], auto[mask], metric="cosine")) \
                    if len(set(auto[mask].tolist())) >= 2 else 0.0
            except Exception:
                score = 0.0
            if score >= OVERRIDE_MIN_SCORE:
                print(f"[diarizer] the recording said {num_speakers_hint} speaker(s), the voices make {found} "
                      f"(silhouette {score:.2f}): {found} are kept", flush=True)
                return auto
            print(f"[diarizer] {found} voices found against {num_speakers_hint} said, not sure enough "
                  f"(silhouette {score:.2f}): the count said is kept", flush=True)
    if n_samples == 1 or num_speakers_hint == 1:
        print(f"[diarizer] one speaker: {'one phrase' if n_samples == 1 else 'the recording says one speaker'}", flush=True)
        return np.zeros(n_samples, dtype=int)
    # A count said: the voices are first grouped as in Auto (up to max_speakers, close voices joined),
    # and the count is the most there may be. Searched only within 2..count, the split scoring best
    # was often a smaller one: four people of a meeting became three, and more phrases went to the
    # wrong person than in Auto (AMI: 14 % of the time against 6 %, bench-report/diarization.md)
    if num_speakers_hint > 1:
        auto = _determine_clusters(embeddings, durations, 0, max(max_speakers, num_speakers_hint))
        found = len(set(auto.tolist()))
        if 2 <= found <= num_speakers_hint:
            print(f"[diarizer] {found} voice(s), as in Auto, within the {num_speakers_hint} said", flush=True)
            return auto
        if found > num_speakers_hint:
            print(f"[diarizer] {found} voices against {num_speakers_hint} said: the least heard taken apart", flush=True)
            return _fold_least_heard(embeddings, durations, auto, num_speakers_hint)
        # Auto heard one voice: the count said decides how many there are (below)

    # Filter reliable anchor segments (duration >= 2.2s) to determine speaker clusters
    # Short emotional phrases (< 2.2s) have higher pitch/timbre variance in ECAPA space
    anchor_mask = durations >= 2.2
    if np.sum(anchor_mask) < 2:
        anchor_mask = durations >= 1.4
    if np.sum(anchor_mask) < 2:
        anchor_mask = np.ones(n_samples, dtype=bool)

    anchor_embs = embeddings[anchor_mask]
    anchor_durs = durations[anchor_mask]
    dist_matrix = cosine_distances(anchor_embs)

    # In Auto mode (num_speakers_hint <= 0), check if anchor segments belong to a single speaker
    if num_speakers_hint <= 0:
        upper_tri = dist_matrix[np.triu_indices_from(dist_matrix, k=1)]
        if len(upper_tri) > 0:
            p90_dist = float(np.percentile(upper_tri, 90))
            # Same speaker across varying intonation/emotion in ECAPA-TDNN typically stays < 0.48
            if p90_dist < 0.48:
                print(f"[diarizer] one speaker: the voices are alike (p90 distance {p90_dist:.3f} < 0.48, "
                      f"{len(anchor_embs)} anchor phrases)", flush=True)
                return np.zeros(n_samples, dtype=int)

    # Groups too small to be a person (a laugh, a noise, a stray phrase) are set aside and the rest
    # grouped again: with average linkage such phrases became groups of their own, and with a count
    # said (6 from the calendar) five of the six went to them and the whole meeting to one speaker
    total_anchor_dur = float(np.sum(anchor_durs))
    min_cluster_dur = min(
        MAX_MIN_SPEAKER_SECONDS,
        max(MIN_SPEAKER_SECONDS, MIN_SPEAKER_SHARE * total_anchor_dur),
    )
    # A count said is the most there are, not the exact number: it comes from the calendar's
    # invitees or the names in Teams captions, and not everyone invited speaks. The split of 2..count
    # whose voices stand apart best is taken; forced to the count, one person became two or three
    anchor_labels: Optional[np.ndarray] = None
    if num_speakers_hint > 1:
        max_k, best_score = min(num_speakers_hint, len(anchor_embs) - 1), -1.0  # more than one: said so
    else:
        max_k, best_score = min(max_speakers, len(anchor_embs) - 1), 0.25  # Auto: a split must score
    for k in range(2, max_k + 1):
        labels = _group_voices(anchor_embs, anchor_durs, k, min_cluster_dur)
        if labels is None:
            continue
        kept = labels >= 0
        try:
            score = float(silhouette_score(dist_matrix[np.ix_(kept, kept)], labels[kept], metric="precomputed"))
        except Exception:
            continue
        if score > best_score:
            best_score, anchor_labels = score, labels
    if anchor_labels is None and num_speakers_hint > 1 and len(anchor_embs) >= 2:
        # Too few phrases for groups of two or more (a short recording): one group per voice as said
        k = min(num_speakers_hint, len(anchor_embs))
        anchor_labels = AgglomerativeClustering(n_clusters=k, metric="cosine", linkage="average").fit_predict(anchor_embs)

    if anchor_labels is None:
        print(f"[diarizer] one speaker: no split scored above the threshold ({len(anchor_embs)} anchor phrases)", flush=True)
        return np.zeros(n_samples, dtype=int)
    groups = sorted(set(anchor_labels[anchor_labels >= 0].tolist()))
    print(f"[diarizer] {len(groups)} voice group(s) from {len(anchor_embs)} anchor phrases"
          f" ({int(np.sum(anchor_labels < 0))} set aside as too short to be a person)"
          f"{f', {num_speakers_hint} said' if num_speakers_hint > 1 else ''}", flush=True)

    # Duration-weighted speaker centroids
    centroids_list: List[np.ndarray] = []
    cluster_weights: List[float] = []
    for k in groups:
        mask_k = anchor_labels == k
        k_embs = anchor_embs[mask_k]
        k_weights = np.clip(anchor_durs[mask_k], 0.5, 10.0)[:, None]
        c = np.sum(k_embs * k_weights, axis=0)
        norm = np.linalg.norm(c)
        centroids_list.append((c / (norm if norm > 1e-8 else 1.0)).astype(np.float32))
        cluster_weights.append(float(np.sum(anchor_durs[mask_k])))

    # In Auto mode, merge two centroids this close (one voice with a pitch shift). It was 0.46: in a
    # call every voice comes through the same codec and different people's centroids are often
    # 0.35-0.5 apart, so a meeting of several became one or two speakers
    if num_speakers_hint <= 0 and len(centroids_list) > 1:
        keep_indices = list(range(len(centroids_list)))
        keep_indices.sort(key=lambda idx: cluster_weights[idx], reverse=True)
        merged_centroids: List[np.ndarray] = []
        for idx in keep_indices:
            cand = centroids_list[idx]
            if not merged_centroids:
                merged_centroids.append(cand)
                continue
            dists_to_existing = [float(1.0 - np.dot(cand, existing)) for existing in merged_centroids]
            if min(dists_to_existing) >= SAME_VOICE_CENTROIDS:
                merged_centroids.append(cand)
        centroids = np.vstack(merged_centroids)
        if len(centroids) <= 1:
            print(f"[diarizer] one speaker: {len(groups)} groups found, all close enough to be one voice", flush=True)
            return np.zeros(n_samples, dtype=int)
    else:
        centroids = np.vstack(centroids_list)

    # Assign all segments to nearest speaker centroid
    all_dists = cosine_distances(embeddings, centroids)
    raw_labels = np.argmin(all_dists, axis=1)

    # Re-index speakers in chronological order of first appearance (SPEAKER_00 = first person to speak)
    ordered_map: Dict[int, int] = {}
    final_labels = np.zeros(n_samples, dtype=int)
    for i, lbl in enumerate(raw_labels):
        lbl_int = int(lbl)
        if lbl_int not in ordered_map:
            ordered_map[lbl_int] = len(ordered_map)
        final_labels[i] = ordered_map[lbl_int]

    return final_labels


def diarize_and_merge_segments(
    wav_path: str | Path,
    raw_segments: List[Dict[str, Any]],
    device: str = "cuda",
    num_speakers_hint: int = 0,
    diarization_enabled: bool = True,
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Assigns speaker IDs (SPEAKER_00, SPEAKER_01, ...) to transcript segments without requiring
    any external tokens or API keys, smooths short interjections, and merges consecutive
    turns from the same speaker into readable dialogue paragraphs.
    """
    if not raw_segments:
        return {}, []

    if not diarization_enabled:
        print("[diarizer] one speaker: splitting by voices is off for this recording", flush=True)
        speakers = {
            "SPEAKER_00": {
                "id": "SPEAKER_00",
                "name": "Участник 1",
                "color": SPEAKER_COLORS[0],
                "sample_start": raw_segments[0]["start"],
                "sample_end": min(raw_segments[0]["end"], raw_segments[0]["start"] + 6.0),
            }
        }
        merged = _merge_consecutive_speaker_segments(
            [{**seg, "speaker": "SPEAKER_00"} for seg in raw_segments]
        )
        return speakers, merged

    if progress_callback:
        progress_callback(68, "Подготовка фрагментов речи для разделения участников...")

    fine_segments = _split_segments_by_word_pauses(raw_segments)

    # Nemotron 3 Diarization, when chosen in the settings: who speaks when for the whole recording
    # (app/nemotron_diar.py). ECAPA below still makes the voice prints. Any failure: ECAPA alone.
    turns: Optional[List[Tuple[float, float, int]]] = None
    if num_speakers_hint != 1:
        from app import nemotron_diar

        if nemotron_diar.usable():
            if progress_callback:
                progress_callback(70, "Разметка «кто когда говорит» (Nemotron)...")
            try:
                turns = nemotron_diar.turns(wav_path, device=device) or None
                if turns:
                    found = len({t[2] for t in turns})
                    print(f"[diarizer] Nemotron: {found} speaker(s), {len(turns)} turns", flush=True)
                    fine_segments = _split_by_turns(fine_segments, turns)
                else:
                    print("[diarizer] Nemotron marked no speech: ECAPA groups the voices", flush=True)
            except Exception as e:
                if type(e).__name__ == "JobCancelled":
                    raise
                print(f"[diarizer] Nemotron failed ({str(e).splitlines()[0][:200] if str(e) else type(e).__name__}): "
                      "ECAPA groups the voices", flush=True)
                turns = None

    if progress_callback:
        progress_callback(72, "Загрузка голосовой модели ECAPA-TDNN (без токенов)...")

    audio_data, sr = sf.read(str(wav_path), dtype="float32")
    if audio_data.ndim > 1:
        audio_data = np.mean(audio_data, axis=1)

    encoder = _get_ecapa_encoder(device=device)

    valid_indices: List[int] = []
    durations_list: List[float] = []
    chunks: List[np.ndarray] = []
    for idx, seg in enumerate(fine_segments):
        chunk = _prepare_slice(audio_data, sr, float(seg["start"]), float(seg["end"]))
        if chunk is not None:
            chunks.append(chunk)
            valid_indices.append(idx)
            durations_list.append(float(seg["end"]) - float(seg["start"]))

    def _embed_progress(done: int, total: int) -> None:
        if progress_callback:
            progress_callback(74 + int(10 * done / max(1, total)), f"Анализ тембра голосов ({done}/{total})...")

    try:
        embeddings_list = _embed_slices(encoder, chunks, _embed_progress) if chunks else []
    except Exception as e:  # torch.AcceleratorError and the like: the video card failed, the processor does it
        if _ecapa_device == "cpu" or type(e).__name__ == "JobCancelled":
            raise
        print(f"[diarizer] the video card failed ({str(e).splitlines()[0][:160]}): again on the processor", flush=True)
        unload_diarizer()
        if progress_callback:
            progress_callback(74, "Видеокарта не справилась — разделение участников на процессоре...")
        encoder = _get_ecapa_encoder(device="cpu")
        embeddings_list = _embed_slices(encoder, chunks, _embed_progress) if chunks else []

    # Free diarizer VRAM immediately after embedding extraction
    unload_diarizer()

    if progress_callback:
        progress_callback(86, "Разделение участников по голосам...")

    speaker_assignments = [0] * len(fine_segments)

    if turns:
        embs_arr = np.vstack(embeddings_list) if embeddings_list else None
        durs_arr = np.array(durations_list, dtype=np.float32)
        speaker_assignments = _labels_from_turns(fine_segments, valid_indices, embs_arr, durs_arr, turns,
                                                 num_speakers_hint=num_speakers_hint)
    elif len(embeddings_list) >= 2:
        embs_arr = np.vstack(embeddings_list)
        durs_arr = np.array(durations_list, dtype=np.float32)
        labels = _determine_clusters(embs_arr, durs_arr, num_speakers_hint=num_speakers_hint)

        for valid_pos, seg_idx in enumerate(valid_indices):
            speaker_assignments[seg_idx] = int(labels[valid_pos])

        # Fill in very short segments that had no embedding using nearest valid neighbor
        valid_set = set(valid_indices)
        for i in range(len(fine_segments)):
            if i not in valid_set:
                # Find closest valid index
                closest = min(valid_indices, key=lambda v: abs(v - i))
                speaker_assignments[i] = speaker_assignments[closest]

        # Temporal collar smoothing: if a short segment (< 2.2s) is surrounded by the same speaker, smooth it
        for i in range(1, len(fine_segments) - 1):
            dur = float(fine_segments[i]["end"]) - float(fine_segments[i]["start"])
            if dur < 2.2 and speaker_assignments[i - 1] == speaker_assignments[i + 1]:
                speaker_assignments[i] = speaker_assignments[i - 1]

    # Voice print per speaker for voice profiles: duration-weighted mean of its embeddings
    voice_prints: Dict[str, List[float]] = {}
    if embeddings_list:
        sums: Dict[int, np.ndarray] = {}
        for valid_pos, seg_idx in enumerate(valid_indices):
            num = speaker_assignments[seg_idx]
            vec = np.asarray(embeddings_list[valid_pos], dtype=np.float32) * durations_list[valid_pos]
            sums[num] = sums.get(num, 0) + vec
        for num, vec in sums.items():
            norm = float(np.linalg.norm(vec))
            if norm > 1e-8:
                voice_prints[f"SPEAKER_{num:02d}"] = [round(float(x), 5) for x in vec / norm]

    labeled_segments = []
    for seg, spk_num in zip(fine_segments, speaker_assignments):
        spk_id = f"SPEAKER_{spk_num:02d}"
        labeled_segments.append({**seg, "speaker": spk_id})

    merged_segments = _merge_consecutive_speaker_segments(labeled_segments)

    # Build speaker metadata with best voice sample for audio preview in UI
    speakers_meta: Dict[str, Dict[str, Any]] = {}
    unique_speakers = sorted({seg["speaker"] for seg in merged_segments})

    for idx, spk_id in enumerate(unique_speakers):
        spk_segs = [s for s in merged_segments if s["speaker"] == spk_id]
        # Pick the clearest segment between 2.5s and 8s for voice preview
        best_seg = max(
            spk_segs,
            key=lambda s: min(6.0, float(s["end"]) - float(s["start"])),
        )
        s_start = round(float(best_seg["start"]), 2)
        s_end = round(min(float(best_seg["end"]), s_start + 6.0), 2)

        speakers_meta[spk_id] = {
            "id": spk_id,
            "name": f"Участник {idx + 1}",
            "color": SPEAKER_COLORS[idx % len(SPEAKER_COLORS)],
            "sample_start": s_start,
            "sample_end": s_end,
        }
        if spk_id in voice_prints:
            speakers_meta[spk_id]["embedding"] = voice_prints[spk_id]

    return speakers_meta, merged_segments


def _merge_consecutive_speaker_segments(
    segments: List[Dict[str, Any]],
    max_pause_gap: float = 1.6,
    max_merged_duration: float = 38.0,
) -> List[Dict[str, Any]]:
    """
    Merges consecutive segments belonging to the same speaker into readable dialogue turns
    while preserving word-level timestamps for interactive player highlighting.
    """
    if not segments:
        return []

    merged: List[Dict[str, Any]] = []
    current = dict(segments[0])
    current["words"] = list(current.get("words") or [])

    for nxt in segments[1:]:
        same_speaker = nxt.get("speaker") == current.get("speaker")
        gap = float(nxt["start"]) - float(current["end"])
        combined_dur = float(nxt["end"]) - float(current["start"])

        if same_speaker and gap <= max_pause_gap and combined_dur <= max_merged_duration:
            current["end"] = round(float(nxt["end"]), 2)
            current["text"] = (current["text"].rstrip() + " " + nxt["text"].lstrip()).strip()
            current["words"].extend(nxt.get("words") or [])
        else:
            current["id"] = len(merged) + 1
            merged.append(current)
            current = dict(nxt)
            current["words"] = list(current.get("words") or [])

    current["id"] = len(merged) + 1
    merged.append(current)
    return merged
