# Bench tool of 2026-11-14 (bench-report/llm-profiles.md, embeddings.md, diarization.md). Paths point to the
# benchmark workspace C:s-llm (data copy, separate Ollama, downloads); adjust them to rerun.
"""Semantic-search benchmark on the processor: Recall@5 and MRR@10 over the whole library of the data copy,
index time per hour of audio, peak RAM. Original weights through sentence-transformers; the Ollama builds
(what the app runs) through /api/embed for bge-m3 and qwen3-embedding:0.6b."""
import json, glob, os, re, sys, time, threading
import numpy as np, psutil, httpx
torch_threads = None
CORPUS = json.load(open(r'C:\vs-llm\emb-corpus.json', encoding='utf-8'))
QS = []
for p in glob.glob(r'C:\vs-llm\search-questions\*.json'):
    mid = int(os.path.basename(p)[:-5])
    for q in json.load(open(p, encoding='utf-8')):
        QS.append(dict(q, meeting=mid))
def secs(t):
    s = 0
    for x in t.split(':'): s = s * 60 + int(x)
    return s
docs, owner = [], []
for m in CORPUS:
    for k, (start, sp, text) in enumerate(m['chunks']):
        docs.append(text); owner.append((m['id'], k, start))
idx = {}
for i, (mid, k, start) in enumerate(owner): idx.setdefault(mid, []).append((start, i))
def gold(q):
    g = set()
    for t in q['at']:
        s = secs(t); best = None
        for start, i in idx[q['meeting']]:
            if start <= s + 0.999: best = i
        if best is not None: g.add(best)
    return g
GOLD = [gold(q) for q in QS]
HOURS = sum(m['duration'] for m in CORPUS) / 3600

class Peak(threading.Thread):
    def __init__(self, pids):
        super().__init__(daemon=True); self.pids = pids; self.peak = 0; self.run_ = True
    def run(self):
        while self.run_:
            tot = 0
            for p in self.pids():
                try: tot += psutil.Process(p).memory_info().rss
                except Exception: pass
            self.peak = max(self.peak, tot); time.sleep(0.2)

def evaluate(Q, D):
    S = Q @ D.T
    r5 = mrr = 0.0; per = []
    for i, g in enumerate(GOLD):
        order = np.argsort(-S[i])[:10]
        rank = next((j + 1 for j, d in enumerate(order) if d in g), None)
        r5 += 1 if rank and rank <= 5 else 0; mrr += 1 / rank if rank else 0
        per.append(rank)
    n = len(GOLD)
    return round(r5 / n, 3), round(mrr / n, 3), per

def norm(x): x = np.asarray(x, dtype=np.float32); return x / np.linalg.norm(x, axis=1, keepdims=True)

def st_model(name, qpre='', dpre='', qprompt=None, **kw):
    from sentence_transformers import SentenceTransformer
    pk = Peak(lambda: [os.getpid()]); pk.start()
    t0 = time.time(); m = SentenceTransformer(name, device='cpu', **kw); load = time.time() - t0
    m.encode(['прогрев'] * 4)
    t0 = time.time(); D = m.encode([dpre + d for d in docs], batch_size=16, normalize_embeddings=True); idx_t = time.time() - t0
    t0 = time.time()
    if qprompt: Q = m.encode([q['q'] for q in QS], prompt=qprompt, normalize_embeddings=True)
    else: Q = m.encode([qpre + q['q'] for q in QS], normalize_embeddings=True)
    q_t = (time.time() - t0) / len(QS)
    pk.run_ = False
    return D, Q, load, idx_t, q_t, pk.peak

OLL = 'http://127.0.0.1:11435'
def ollama_model(name):
    def runner_pids():
        return [p.pid for p in psutil.process_iter(['name']) if p.info['name'] in ('llama-server.exe', 'ollama_llama_server.exe')] + \
               [p.pid for p in psutil.process_iter(['name', 'cmdline']) if p.info['name'] == 'ollama.exe' and 'runner' in ' '.join(p.info['cmdline'] or [])]
    c = httpx.Client(timeout=600)
    def emb(texts):
        out = []
        for i in range(0, len(texts), 16):
            r = c.post(OLL + '/api/embed', json={'model': name, 'input': texts[i:i + 16], 'options': {'num_gpu': 0}, 'keep_alive': '10m'})
            out += r.json()['embeddings']
        return norm(out)
    t0 = time.time(); emb(['прогрев']); load = time.time() - t0
    pk = Peak(runner_pids); pk.start()
    t0 = time.time(); D = emb(docs); idx_t = time.time() - t0
    t0 = time.time(); Q = emb([q['q'] for q in QS]); q_t = (time.time() - t0) / len(QS)
    pk.run_ = False
    c.post(OLL + '/api/generate', json={'model': name, 'keep_alive': 0})
    return D, Q, load, idx_t, q_t, pk.peak

MODELS = {
  'BAAI/bge-m3': lambda: st_model('BAAI/bge-m3', revision='5617a9f61b028005a4858fdac845db406aefb181'),
  'deepvk/USER-bge-m3': lambda: st_model('deepvk/USER-bge-m3', revision='0cc6cfe48e260fb0474c753087a69369e88709ae'),
  'Qwen/Qwen3-Embedding-0.6B': lambda: st_model('Qwen/Qwen3-Embedding-0.6B', qprompt='Instruct: Given a search query, retrieve the passage of a meeting transcript that answers it\nQuery: ', revision='97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3'),
  'intfloat/multilingual-e5-small': lambda: st_model('intfloat/multilingual-e5-small', qpre='query: ', dpre='passage: ', revision='614241f622f53c4eeff9890bdc4f31cfecc418b3'),
  'ollama:bge-m3': lambda: ollama_model('bge-m3'),
  'ollama:qwen3-embedding:0.6b': lambda: ollama_model('qwen3-embedding:0.6b'),
}
out = open(r'C:\vs-llm\results\embeddings.jsonl', 'a', encoding='utf-8')
for name in (sys.argv[1:] or MODELS):
    for attempt in (1, 2):  # the second pass goes to the report: the first warms the disk cache
        D, Q, load, idx_t, q_t, peak = MODELS[name]()
    r5, mrr, per = evaluate(Q, D)
    langs = {}
    for q, rank in zip(QS, per):
        k = f"{q['lang']}->{'en' if q['meeting'] in (4,) else 'mixed' if q['meeting']==87 else 'ru'}"
        a = langs.setdefault(k, [0, 0]); a[0] += 1 if rank and rank <= 5 else 0; a[1] += 1
    rec = dict(model=name, questions=len(QS), chunks=len(docs), hours=round(HOURS, 2), recall5=r5, mrr10=mrr,
               index_sec=round(idx_t, 1), index_sec_per_hour=round(idx_t / HOURS, 1), query_ms=round(q_t * 1000),
               load_sec=round(load, 1), peak_ram_gb=round(peak / 2**30, 2), dim=int(D.shape[1]),
               by_lang={k: f"{a}/{b}" for k, (a, b) in langs.items()}, ranks=per)
    out.write(json.dumps(rec, ensure_ascii=False) + '\n'); out.flush()
    print(json.dumps({k: v for k, v in rec.items() if k != 'ranks'}, ensure_ascii=False), flush=True)
