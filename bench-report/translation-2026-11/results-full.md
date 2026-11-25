# Translation bench, 2026-11-24 15:49

Data: google/wmt24pp en-ru_RU.jsonl (Apache-2.0), 100 lines of 5-30 words; ru→en is the same pairs reversed (the Russian side is itself a translation).
PC: Windows 10, AMD64 Family 25 Model 97 Stepping 2, AuthenticAMD, 32 threads, CUDA devices seen by CTranslate2: 1. Ollama 0.40.8.

| Model | Licence | Lines | chrF++ en→ru | chrF++ ru→en | COMET en→ru | COMET ru→en | s/line en→ru (median / p90) | s/line ru→en (median / p90) | File, MB | Loaded, MB (of it VRAM) | Card in use, MB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gemma4:e2b | Apache-2.0 | 100 | 41.3 | 42.4 | 0.783 | 0.788 | 0.18 / 0.27 | 0.15 / 0.22 | 4375 | 313 (313) | 9002 |
| gemma4:e4b | Apache-2.0 | 100 | 44.8 | 43.5 | 0.817 | 0.793 | 0.23 / 0.38 | 0.18 / 0.28 | 6279 | 350 (350) | 10647 |
| translategemma:4b | Gemma Terms of Use (own terms, use restrictions) ⚠ | 100 | 41.3 | 42.8 | 0.833 | 0.804 | 0.20 / 0.31 | 0.17 / 0.26 | 3146 | 2746 (2746) | 9652 |
| translategemma:4b@app | Gemma Terms of Use (own terms, use restrictions) ⚠ | 100 | 40.1 | 41.2 | 0.819 | 0.790 | 0.21 / 0.36 | 0.18 / 0.29 | 3146 | 2746 (2746) | 9655 |
| translategemma:12b | Gemma Terms of Use (own terms, use restrictions) ⚠ | 100 | 45.3 | 43.7 | 0.838 | 0.800 | 0.44 / 0.70 | 0.35 / 0.56 | 7734 | 7677 (7677) | 14719 |
| opus-mt | Apache-2.0 (en-ru) / CC-BY-4.0 (ru-en) | 100 | 34.3 | 37.8 | 0.701 | 0.747 | 0.07 / 0.18 | 0.05 / 0.10 | 79 + 79 | — | — |
| hy-mt3-1.8b-fix | Apache-2.0 | 100 | 42.5 | 42.7 | 0.813 | 0.793 | 0.16 / 0.28 | 0.10 / 0.16 | 1286 | 1463 (1463) | 4027 |
| hf.co/tencent/Hy-MT3-7B-GGUF:Q4_K_M | Apache-2.0 | 100 | 45.7 | 45.6 | 0.836 | 0.802 | 0.38 / 0.72 | 0.21 / 0.35 | 4907 | 5274 (5274) | 7838 |

⚠ — licence not plainly free for commercial use: check before adopting.
File: the model on disk (gemma4 includes its vision and audio parts). Loaded: what Ollama reports for the model with the captions' context (2048). Card in use: nvidia-smi for the whole card right after the model was loaded, other programs included.
