# Bench tool of 2026-11-15 (bench-report/diarization.md): voiceprint quality apart from the app grouping.
# Paths point to the benchmark workspace C:s-llm; adjust them to rerun.
"""Voiceprint quality apart from the app's grouping: single-speaker AMI segments (RTTM, no overlap, 1.5-10 s),
one embedding per segment, EER of same-speaker vs different-speaker cosine within each meeting, and the
distribution of cosine distances (where the app's ECAPA-tuned thresholds sit)."""
import sys, json
sys.path.insert(0, r"D:\src\VerbaScribe-pc")
import numpy as np, soundfile as sf, torch, torchaudio
import onnxruntime as ort
from huggingface_hub import hf_hub_download

MEET = ["ES2004a", "IS1009a", "TS3003b", "EN2002b"]


def segments(ami):
    rows = []
    for l in open(rf"C:\vs-llm\ami\{ami}.rttm"):
        p = l.split(); s, d = float(p[3]), float(p[4]); rows.append((s, s + d, p[7]))
    rows.sort()
    out = []
    for i, (s, e, spk) in enumerate(rows):
        if e - s < 1.5: continue
        if any(o_s < e and o_e > s for j, (o_s, o_e, _) in enumerate(rows) if j != i): continue  # overlap
        out.append((s, min(e, s + 10), spk))
    return out


def onnx_enc(repo, f, scale=32768.0, cmn=True):
    sess = ort.InferenceSession(hf_hub_download(repo, f), providers=["CPUExecutionProvider"])
    def emb(w):
        x = torch.from_numpy(w).unsqueeze(0) * scale
        fb = torchaudio.compliance.kaldi.fbank(x, num_mel_bins=80, frame_length=25, frame_shift=10, dither=0.0,
                                               sample_frequency=16000, window_type="hamming")
        if cmn: fb = fb - fb.mean(0, keepdim=True)
        return sess.run(None, {"feats": fb.unsqueeze(0).numpy().astype(np.float32)})[0].reshape(-1)
    return emb


def ecapa_enc():
    from app import diarizer
    enc = diarizer._get_ecapa_encoder(device="cpu")
    def emb(w):
        with torch.no_grad():
            return enc.encode_batch(torch.from_numpy(w).unsqueeze(0)).reshape(-1).numpy()
    return emb


def eer(same, diff):
    th = np.sort(np.concatenate([same, diff]))
    best = 1.0
    for t in th[:: max(1, len(th) // 2000)]:
        frr = np.mean(same < t); far = np.mean(diff >= t); best = min(best, max(frr, far))
    return best


ENC = {
    "ecapa": ecapa_enc,
    "resnet34-LM": lambda: onnx_enc("Wespeaker/wespeaker-voxceleb-resnet34-LM", "voxceleb_resnet34_LM.onnx"),
    "campplus-LM": lambda: onnx_enc("Wespeaker/wespeaker-voxceleb-campplus-LM", "voxceleb_CAM++_LM.onnx"),
    "campplus-LM no-CMN": lambda: onnx_enc("Wespeaker/wespeaker-voxceleb-campplus-LM", "voxceleb_CAM++_LM.onnx", cmn=False),
}
res = {}
for name, mk in ENC.items():
    emb = mk(); same_all, diff_all, eers = [], [], []
    for ami in MEET:
        audio, sr = sf.read(rf"C:\vs-llm\ami\{ami}.wav", dtype="float32")
        if audio.ndim > 1: audio = audio.mean(1)
        segs = segments(ami)[:120]
        E = np.stack([emb(audio[int(s * sr):int(e * sr)]) for s, e, _ in segs])
        E /= np.linalg.norm(E, axis=1, keepdims=True)
        S = E @ E.T; lab = np.array([k for _, _, k in segs])
        iu = np.triu_indices(len(segs), 1)
        same = S[iu][lab[iu[0]] == lab[iu[1]]]; diff = S[iu][lab[iu[0]] != lab[iu[1]]]
        eers.append(eer(same, diff)); same_all += list(same); diff_all += list(diff)
    res[name] = {"eer_mean": round(float(np.mean(eers)), 3), "eer_per_meeting": [round(float(x), 3) for x in eers],
                 "cos_same_median": round(float(np.median(same_all)), 3), "cos_diff_median": round(float(np.median(diff_all)), 3)}
    print(name, res[name], flush=True)
json.dump(res, open(r"C:\vs-llm\results\spk-eer.json", "w"), indent=1)
