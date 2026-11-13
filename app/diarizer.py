import inspect
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
        if not words or len(words) <= 2:
            refined.append(seg)
            continue

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

    if len(embeddings_list) >= 2:
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
