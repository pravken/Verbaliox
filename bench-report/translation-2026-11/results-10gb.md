# Translation bench, 2026-11-24 15:56

Data: google/wmt24pp en-ru_RU.jsonl (Apache-2.0), 100 lines of 5-30 words; ru→en is the same pairs reversed (the Russian side is itself a translation).
PC: Windows 10, AMD64 Family 25 Model 97 Stepping 2, AuthenticAMD, 32 threads, CUDA devices seen by CTranslate2: 1. Ollama 0.40.8.

| Model | Licence | Lines | chrF++ en→ru | chrF++ ru→en | COMET en→ru | COMET ru→en | s/line en→ru (median / p90) | s/line ru→en (median / p90) | File, MB | Loaded, MB (of it VRAM) | Card in use, MB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gemma4:e4b | Apache-2.0 | 100 | 44.9 | 43.8 | 0.818 | 0.794 | 0.24 / 0.39 | 0.18 / 0.28 | 6279 | 350 (350) | 20861 |
| translategemma:12b | Gemma Terms of Use (own terms, use restrictions) ⚠ | 100 | 45.6 | 43.9 | 0.839 | 0.802 | 0.45 / 0.76 | 0.36 / 0.57 | 7734 | 7677 (7677) | 24100 |
| hf.co/tencent/Hy-MT3-7B-GGUF:Q4_K_M | Apache-2.0 | 100 | 45.8 | 45.1 | 0.835 | 0.800 | 0.40 / 0.74 | 0.21 / 0.40 | 4907 | 5274 (5274) | 20574 |
| gemma4:e2b | Apache-2.0 | 100 | 41.6 | 42.4 | 0.783 | 0.788 | 0.19 / 0.29 | 0.15 / 0.24 | 4375 | 313 (313) | 18231 |
| hy-mt3-1.8b-fix | Apache-2.0 | 100 | 41.9 | 42.5 | 0.819 | 0.793 | 0.16 / 0.29 | 0.10 / 0.17 | 1286 | 1463 (1463) | 16772 |

⚠ — licence not plainly free for commercial use: check before adopting.
File: the model on disk (gemma4 includes its vision and audio parts). Loaded: what Ollama reports for the model with the captions' context (2048). Card in use: nvidia-smi for the whole card right after the model was loaded, other programs included.
