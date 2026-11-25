# Translation bench, 2026-11-24 18:54

Data: google/wmt24pp en-ru_RU.jsonl (Apache-2.0), 100 lines of 5-30 words; ru→en is the same pairs reversed (the Russian side is itself a translation).
PC: Windows 10, AMD64 Family 25 Model 97 Stepping 2, AuthenticAMD, 32 threads, CUDA devices seen by CTranslate2: 1. Ollama 0.40.8.

| Model | Licence | Lines | chrF++ en→ru | chrF++ ru→en | s/line en→ru (median / p90) | s/line ru→en (median / p90) | File, MB | Loaded, MB (of it VRAM) | Card in use, MB |
|---|---|---|---|---|---|---|---|---|---|
| hf.co/tencent/Hy-MT3-7B-GGUF:Q4_K_M@app | Apache-2.0 | 100 | 46.3 | 45.6 | 0.42 / 0.75 | 0.23 / 0.39 | 4907 | 5274 (5274) | 7065 |

⚠ — licence not plainly free for commercial use: check before adopting.
File: the model on disk (gemma4 includes its vision and audio parts). Loaded: what Ollama reports for the model with the captions' context (2048). Card in use: nvidia-smi for the whole card right after the model was loaded, other programs included.
