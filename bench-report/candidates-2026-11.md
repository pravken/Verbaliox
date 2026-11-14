# Кандидаты моделей для следующих замеров Verbaliox (2026-11-14)

Главный профиль — **RTX 3080 10 ГБ**, дальше 8 ГБ, 6 ГБ и только процессор. RTX 3090 24 ГБ — машина для замеров, у пользователей она встречается редко. Главный раздел отчёта — LLM (раздел 2). Остальные направления даны коротко (раздел 3).

## 0. Как проверялись факты

- **Hugging Face, ollama.com, arxiv.org и modelscope.cn из этой сессии недоступны:** прокси отклоняет соединение. Карточки HF напрямую не открывались. Лицензии взяты из трёх источников:
  1. файл `LICENSE` или README на GitHub, скачанный через `raw.githubusercontent.com`. В таблицах помечено **[GH]**, это первоисточник;
  2. выдержки из карточек HF в результатах веб-поиска. Помечено **[HF через поиск]**: поле `license:` цитирует поисковик, саму карточку я не открывал;
  3. зеркала и агрегаторы (featherless, mixpeek и т. п.). Помечено **[вторично]**.
- Перед включением модели в программу всё с пометками [HF через поиск] и [вторично] нужно один раз открыть на HF (поле `license` и файл LICENSE). Так требует CLAUDE.md, и это стоит сделать до замеров.
- Цифры видеопамяти для KV-кэша и подходящего контекста **рассчитаны мной** (формула в 2.2), это не замеры. Параметры архитектуры, взятые по памяти, помечены «по памяти». Скорости с сайтов-агрегаторов — ориентиры, а не замеры.
- Что уже замерено и что отвергнуто (`bench-report/`), сюда не повторяется: GigaAM v3, GigaAM Multilingual, Parakeet v3, Canary v2, Whisper large-v3/turbo, T-one, Qwen3-8B, Qwen3.5 4B/9B, Qwen2.5 1.5B/14B, VoxCPM2 и прочие TTS.

---

## 1. Конкуренты → стек

### 1.1 Открытые (README и код на GitHub)

| Проект | ASR | Диаризация / VAD | LLM | Прочее | Источник |
|---|---|---|---|---|---|
| **Meetily** (Zackriya-Solutions/meeting-minutes) | Whisper (whisper.cpp; на Windows сборка Vulkan) и **Parakeet TDT 0.6B v3 в ONNX от istupakov** — тот же экспорт, что у нас | В бесплатной версии нет. «Speaker identification» — в платной PRO | Ollama (рекомендуется), а также Claude, Groq, OpenRouter и OpenAI-совместимые | Встроенная офлайн-LLM (по одному обзору Qwen 3.5) — не проверено | [README](https://github.com/Zackriya-Solutions/meeting-minutes), [обзор dev.to](https://dev.to/dibi8/meetily-privacy-first-ai-meeting-assistant-with-local-stt-18k-stars-pod) |
| **Hyprnote → anarlog** (fastrepl/hyprnote) | Локальные модели на Mac (MLX); облако Soniox в Pro | Rust-крейты `crates/*` с диаризацией; модели не названы | Свой HyprLLM (дообученный Qwen3 1.7B) или Ollama / LM Studio | Проект переименован в anarlog | [README](https://github.com/fastrepl/hyprnote), [Launch HN](https://hn.svelte.dev/item/44725306) |
| **Scriberr** | Whisper (WhisperX), **NVIDIA Parakeet, Canary** | PyAnnote и NVIDIA NeMo (скачивает обе) | Ollama / OpenAI-совместимые | — | [README](https://github.com/rishikanthc/Scriberr) |
| **WhisperX** | faster-whisper (batched) | **pyannote speaker-diarization-community-1** | — | Выравнивание слов — wav2vec2 (`WAV2VEC2_ASR_LARGE_LV60K_960H` и модели по языкам) | [README](https://github.com/m-bain/whisperX) |
| **whisper-diarization** (MahmoudAshraf97) | faster-whisper | NeMo: **MarbleNet** (VAD), **TitaNet** (эмбеддинги), MSDD | — | Demucs выделяет голос; `ctc-forced-aligner` (код BSD-2, а веса MMS — **CC-BY-NC**, см. 3.9) | [README](https://github.com/MahmoudAshraf97/whisper-diarization) |
| **noScribe** | faster-whisper | pyannote | — | — | [README](https://github.com/kaixxx/noScribe) |
| **aTrain** | faster-whisper | pyannote | — | — | [README](https://github.com/JuergenFleiss/aTrain) |
| **Buzz** | Whisper, whisper.cpp (Vulkan), HF-модели Whisper | «Speaker identification»; движок не проверен | — | Перевод | [README](https://github.com/chidiwilliams/buzz) |
| **Vibe** | whisper.cpp, **Parakeet TDT v3, Nemotron 3.5** | `pyannote-rs`: **segmentation-3.0** и **wespeaker-voxceleb-resnet34-LM** в ONNX | Ollama | — | [README](https://github.com/thewh1teagle/vibe), [pyannote-rs](https://github.com/thewh1teagle/pyannote-rs) |
| **Handy** (диктовка) | Whisper (GGML), **Parakeet V3**, Parakeet Unified EN (GGUF) | **Silero** VAD | — | — | [README](https://github.com/cjpais/Handy) |
| **OpenWhispr** | Whisper (whisper.cpp), **Parakeet** (sherpa-onnx), Cohere Transcribe | sherpa-onnx: Silero VAD, **pyannote-segmentation-3.0**, **CAM++ (3D-Speaker, voxceleb, 512-мерный)**, агломеративная кластеризация с порогом 0,5. Голосовые отпечатки людей хранятся в SQLite | llama.cpp и облачные модели | Семантический поиск на локальных эмбеддингах | [README](https://github.com/HeroTools/open-whispr), [блог о диаризации](https://openwhispr.com/blog/local-speaker-diarization) |
| **Speakr** | WhisperX (свой контейнер) или облака (OpenAI, Voxtral, AssemblyAI) | WhisperX (pyannote); **голосовые профили через эмбеддинги** | Ollama, OpenRouter | — | [README](https://github.com/murtaza-nasir/speakr) |
| **Screenpipe** | Whisper large-v3-turbo локально или Deepgram | Есть «speaker identification»; модель не проверена | Ollama | — | [README](https://github.com/mediar-ai/screenpipe) |
| **VoiceInk** (Mac) | whisper.cpp, Parakeet через FluidAudio | — | — | — | [README](https://github.com/Beingpax/VoiceInk) |
| **FluidAudio** (SDK для Mac; на нём VoiceInk и другие) | Parakeet v2/v3 в CoreML | pyannote-сегментация, WeSpeaker, **LS-EEND**, Silero VAD | — | — | [README](https://github.com/FluidInference/FluidAudio) |
| **Amurex** | Расширение Chrome с облачным бэкендом; модели в README не названы | — | — | — | [README](https://github.com/thepersonalaicompany/amurex) |
| **Whishper** | Whisper до large-v3-turbo | — | — | Перевод | [README](https://github.com/pluja/whishper) |

**Выводы по открытым проектам**
- Распознавание у всех — Whisper плюс Parakeet v3. GigaAM и русских ASR не использует никто: здесь у Verbaliox преимущество.
- Диаризация почти везде на pyannote: либо segmentation-3.0 плюс WeSpeaker ResNet34, либо community-1. Альтернативы — CAM++ через sherpa-onnx (OpenWhispr) и NeMo TitaNet.
- Узнавание людей между встречами (голосовые профили) есть у OpenWhispr (CAM++ 512-d) и Speakr (эмбеддинги WhisperX/pyannote).
- LLM у всех через Ollama, конкретную модель почти никто не фиксирует. Hyprnote дообучил свою на Qwen3 1.7B.

### 1.2 Закрытые (по публичным сведениям)

| Продукт | ASR | Диаризация | LLM | Источник / надёжность |
|---|---|---|---|---|
| **Granola** | Deepgram и AssemblyAI | — | OpenAI и Anthropic | [softwaretestinghelp](https://www.softwaretestinghelp.com/?p=411472), [AssemblyAI](https://assemblyai.com/solutions/ai-notetakers); сама Granola провайдеров не называет ([docs](https://docs.granola.ai/help-center/taking-notes/transcription.md)). Вторично |
| **Otter** | Собственный ASR | Собственная | Anthropic (бэкенд ИИ-функций), OpenAI (оценка) | [список субпроцессоров Otter](https://otter.ai/subprocessors), [кейс Anthropic](https://www.anthropic.com/customers/otter). Первоисточник |
| **Fireflies** | «Сторонний ASR плюс собственный» | — | не проверено | [forasoft](https://www.forasoft.com/learn/ai-for-video-engineering/articles-ai/otter-fireflies-fathom-supernormal-ai-meeting-bot-engineering-deep-dive). Вторично |
| **MacWhisper** | WhisperKit, **Parakeet v2/v3**, TDT-CTC-110M, **Qwen3-ASR** | Pro: SpeakerKit от Argmax; по другим данным — Nemotron 3 Diarization (противоречие) | — | [App Store](https://apps.apple.com/app/id6755916880), [heise](https://heise.de/-10322414). Вторично |
| **Superwhisper** | Локально: Whisper (whisper.cpp), Parakeet, **Cohere Transcribe**. Облако: Deepgram Nova 3, ElevenLabs Scribe, свой S1-Voice | В облаке (Nova 3) | — | [docs](https://superwhisper.com/docs/models/voice) |
| **Krisp** | Английский — на устройстве, остальные языки (15+) — на сервере | Есть, качество спорное | — | Шумоподавление и смена акцента — локально, на CPU ([пресс-релиз](https://www.businesswire.com/news/home/20260303945269/en/Krisp-Launches-Listener-Side-Accent-Conversion-for-Meetings-CX-and-Voice-AI-Agents), [обзор](https://dupple.com/reviews/krisp)) |
| **tl;dv, Jamie, Bluedot** | не проверено (вендоры не раскрывают) | Jamie: «запоминает спикеров между встречами» | не проверено | [toolquestor](https://toolquestor.com/vs/jamie-vs-tldv), [G2](https://www.g2.com/compare/bluedot-bluedot-vs-tactiq-vs-tl-dv) |

---

## 2. LLM для саммари, задач и вопросов (главный раздел)

### 2.1 Отбор по лицензии

| Модель | Лицензия | Вердикт | Источник |
|---|---|---|---|
| Qwen3 4B/8B/14B, Qwen3-30B-A3B | Apache-2.0 | ✅ (уже в программе) | README Verbaliox, bench-report |
| **Qwen3.5** 0.8B/2B/4B/9B, 35B-A3B | Apache-2.0 | ✅ | [HF через поиск: Qwen3.5-35B-A3B-Base](https://huggingface.co/Qwen/Qwen3.5-35B-A3B-Base) |
| **Qwen3.6** 27B, 35B-A3B | Apache-2.0 | ✅ | [HF через поиск: unsloth GGUF](https://huggingface.co/unsloth/Qwen3.6-27B-GGUF), [вторично](https://docs.apiyi.com/en/news/qwen-3-6-opensource-launch) |
| **Gemma 4** E2B/E4B/26B-A4B/31B | **Apache-2.0** (впервые у Gemma, апрель 2026) | ✅ (проверить карточку) | [the-decoder](https://the-decoder.com/googles-gemma-4-is-now-available-with-apache-2-0-licensing-for-the-first-time/), [блог Google](https://blog.google/innovation-and-ai/technology/developers-tools/gemma-4/?hl=pt) |
| Gemma 3 4B/12B | Gemma Terms of Use: своя лицензия с запретами на виды использования и правом Google ограничить доступ | ❌ не входит в MIT/Apache/BSD/CC-BY. Вместо неё — Gemma 4 | [the-decoder (про прежнюю лицензию)](https://the-decoder.com/googles-gemma-4-is-now-available-with-apache-2-0-licensing-for-the-first-time/); текст условий не открывался |
| **Phi-4-mini-instruct** (3.8B) | MIT | ✅ | [HF через поиск](https://huggingface.co/microsoft/Phi-4-mini-instruct/blob/main/README.md) |
| Llama 3.1 / 3.2 8B/3B (и Vikhr-Llama-…) | Llama Community License: порог 700 млн MAU, обязательная надпись «Built with Llama», AUP, которую Meta может менять | ❌ своя лицензия, не из списка | [текст лицензии на HF](https://huggingface.co/Mozilla/Meta-Llama-3.1-8B-Instruct-llamafile/blob/7d8b93e61bb828c11a25085aefc28ebf9a7952f2/LICENSE), [meta](https://developer.meta.com/ai/llama3_1/license/) |
| **Ministral 3** 3B/8B/14B (2512) | Apache-2.0 | ✅ | [анонс Mistral](https://mistral.ai/news/mistral-3), [arXiv 2601.08584](https://arxiv.org/html/2601.08584v1) |
| Ministral-8B-2410 (старый) | Mistral Research License (некоммерческая) — по памяти, не проверено | ❌ | — |
| **GigaChat3-10B-A1.8B («Lightning»)**, GigaChat3.1-10B-A1.8B | MIT, «можно в коммерческих продуктах» | ✅ | **[GH] LICENSE и README salute-developers/gigachat3** |
| GigaChat Lite (GigaChat-20B-A3B, 2024) | не проверено | ? | — |
| **T-lite-it-2.1** (8B, база Qwen3-8B) | Apache-2.0 | ✅ (проверить карточку) | [вторично: featherless](https://featherless.ai/models/t-tech/T-lite-it-2.1/readme), [mixpeek](https://mixpeek.com/model/t-tech/T-lite-it-2.1) |
| T-lite-it-1.0 | не проверено | ? | — |
| **QVikhr-3-4B-Instruction** (база Qwen3-4B) | Apache-2.0 | ✅ (проверить карточку) | [вторично: featherless](https://featherless.ai/models/Vikhrmodels/QVikhr-3-4B-Instruction/readme) |
| YandexGPT-5-Lite-8B | Своя лицензия: коммерция только до **10 млн выходных токенов в месяц** | ❌ ограничение объёма | [ScanCode LicenseDB](https://scancode-licensedb.aboutcode.org/yandexgpt-5-lite-8b-2025.html) |
| SmolLM3-3B | Apache-2.0 | ✅, но русского нет среди шести языков | [tinyweights](https://tinyweights.dev/posts/smollm3-3b-vs-phi-4-mini/) (вторично) |
| **gpt-oss-20b** | Apache-2.0 (плюс usage policy в репозитории) | ✅ | [LM Studio](https://lmstudio.ai/models/openai/gpt-oss-20b), [NVIDIA NIM](https://docs.api.nvidia.com/nim/reference/openai-gpt-oss-20b) (вторично) |

### 2.2 Память: веса, KV-кэш, сколько контекста помещается

**Формула.** KV (f16) на один токен = 2 × число слоёв с полным вниманием × число KV-голов × head_dim × 2 байта. В Ollama кэш по умолчанию в f16. `OLLAMA_KV_CACHE_TYPE=q8_0` вместе с `OLLAMA_FLASH_ATTENTION=1` уменьшает его примерно вдвое почти без потери качества ([llmhardware](https://llmhardware.io/guides/kv-cache-quantization-ollama-llama-cpp), [smcleod — автор этой функции в Ollama](https://smcleod.net/2024/12/bringing-k/v-context-quantisation-to-ollama/)). Но настройка серверная и действует на все модели.

**Контекст в программе:** анализ — `LLM_NUM_CTX = 16384` (`app/ollama_client.py`), перевод — 8192, живой перевод — 2048.

**Как считалась колонка «помещается»:** свободно под KV = объём VRAM − веса − 1,0 ГБ (CUDA-контекст, буферы вычислений, рабочий стол). Считается, что ASR в это время выгружен. Значения через «/» — для KV f16 и q8_0. Это расчёт, не замер.

| Модель (Ollama Q4_K_M) | Веса, ГБ | Q5_K_M, ГБ (оценка) | KV на токен (f16) | KV 16k / 32k, ГБ | Помещается: 10 ГБ | 8 ГБ | 6 ГБ |
|---|---|---|---|---|---|---|---|
| **qwen3.5:4b** | 3,4 (каталог программы) | ≈3,9 | 32 КиБ (гибрид: 8 из 32 слоёв с полным вниманием, 4 KV-головы × 256)¹ | 0,5 / 1,0 | 179k / 358k (предел модели 262k) | 115k / 230k | 51k / 102k |
| **qwen3.5:9b** | ≈6,6 с vision-частью ([Ollama-сборки](https://registry.ollama.ai/huihui_ai/qwen3.5-abliterated:9b)); GGUF без vision 5,75 ([modelfit](https://modelfit.io/quant-compare/qwen3.5-9b/)) | ≈6,6–7,5 | 32 КиБ ([config: interval 4, kv 4, head_dim 256](https://huggingface.co/Qwen/Qwen3.5-9B/blob/main/config.json), через поиск) | 0,5 / 1,0 | 77k / 154k | 13k / 26k | — (частичная выгрузка) |
| qwen3:4b / QVikhr-3-4B | ≈2,5 | ≈2,9 | 144 КиБ (36 слоёв × 8 × 128, по памяти) | 2,25 / 4,5 | 46k / 92k (предел 32k, 128k с YaRN) | 32k / 64k | 18k / 36k |
| qwen3:8b / **T-lite-it-2.1** | 5,2 (каталог программы) | ≈5,9 | 144 КиБ | 2,25 / 4,5 | 27k / 54k | 13k / 26k | — |
| qwen3:14b | 9,3 | ≈10,5 | 160 КиБ | 2,5 / 5,0 | — | — | — |
| **phi4-mini** (3.8B) | ≈2,5 (расчёт) | ≈2,8 | 128 КиБ (32 × 8 × 128, по памяти) | 2,0 / 4,0 | 52k / 104k | 36k / 72k | 20k / 40k |
| llama3.1:8b (❌ лицензия, для сравнения) | 4,9 | ≈5,7 | 128 КиБ | 2,0 / 4,0 | 33k / 66k | 17k / 34k | — |
| **ministral-3:8b** | 6,0 с vision ([Ollama](https://registry.ollama.ai/library/ministral-3:8b)) | ≈6,8 | ≈144 КиБ (не проверено) | ≈2,25 / 4,5 | 21k / 43k | 7k / 14k | — |
| ministral-3:14b | 9,1 Ollama / 8,2 GGUF ([HF GGUF](https://huggingface.co/mistralai/Ministral-3-14B-Instruct-2512-GGUF)) | ≈9,7 | не проверено | — | — | — | — |
| **gemma4:e4b** | 6,6–9,5 по тегам ([Ollama](https://registry.ollama.ai/library/gemma4)) | — | Мал: скользящее окно 512 на 5 из 6 слоёв, общий KV у глобальных слоёв ([разбор](https://newsletter.maartengrootendorst.com/i/193064129/kv)) | ≪1 (не проверено) | Помещается при теге 6,6 ГБ | Впритык | — |
| gemma4:e2b | 4,6–7,5 по тегам; QAT ≈4,3 ([Ollama](https://registry.ollama.ai/library/gemma4)) | — | Мал | ≪1 | ✅ | ✅ | QAT-тег |
| **GigaChat3-10B-A1.8B** (MoE, 1,8B активных) | ≈6,5 (расчёт; есть официальный [GGUF](https://huggingface.co/ai-sage/GigaChat3.1-10B-A1.8B-GGUF)) | ≈7,6 | ≈29 КиБ (MLA, оценка; число слоёв не проверено) | ≈0,46 / 0,9 | 88k / 175k | 18k / 35k | Эксперты на CPU |
| **gpt-oss:20b** (MoE, ≈3,6B активных) | 13,8 MXFP4 ([LM Studio](https://lmstudio.ai/models/openai/gpt-oss-20b)) | — | ≈24 КиБ (12 глобальных слоёв × 8 × 64, по памяти) | 0,4 / 0,75 | Эксперты частично на CPU | То же | То же |
| qwen3:30b-a3b (MoE, 3B активных) | ≈18,6 | ≈21,7 | 96 КиБ | 1,5 / 3,0 | Эксперты на CPU | То же | То же |
| **qwen3.6:35b-a3b** / qwen3.5:35b-a3b | ≈22 (оценка) | ≈25 | 20 КиБ (10 слоёв с полным вниманием × 2 KV × 256 по [карточке 35B-A3B](https://huggingface.co/Qwen/Qwen3.5-35B-A3B-Base)) | 0,3 / 0,6 | Эксперты на CPU, нужно ≥32 ГБ ОЗУ | То же | То же |

¹ Для qwen3.5:4b структура взята по аналогии с 9B: в источниках 32 слоя для 4B и 9B ([kaitchup](https://kaitchup.substack.com/p/qwen35-9b-4b-2b-and-08b-gpu-requirements), [besthub](https://besthub.dev/articles/qwen3-5-small-models-unveiled-from-0-8b-to-9b-with-full-capabilities-e409056d2b3c)). Число KV-голов у 4B не проверено. У гибридных моделей вдобавок есть состояние Gated DeltaNet фиксированного размера: от длины контекста оно не растёт.

**Главный вывод по памяти.** У Qwen3.5 и Gemma 4 KV-кэш в 4–5 раз меньше, чем у Qwen3/Llama/Phi. Для протокола длинной встречи (16–32k токенов) это важнее размера весов. На 8 ГБ qwen3:8b помещает лишь 13k контекста в f16, а qwen3.5:4b — больше 100k.

### 2.3 Что держать в памяти одновременно на 10 ГБ

Заметные объёмы видеопамяти по `bench-report/gpu-report.md`: Whisper large-v3-turbo ≈2,1–2,2 ГБ, large-v3 ≈2,4–3,9 ГБ, GigaAM ONNX на CUDA +2–2,5 ГБ, Parakeet на CUDA 3,3–5,4 ГБ. ECAPA — сотни мегабайт (не замерено). Windows с WebView2 держат ещё ~0,3–0,8 ГБ (оценка).

| Сценарий | 10 ГБ | 8 ГБ | 6 ГБ | Только CPU |
|---|---|---|---|---|
| **Во время записи: живые субтитры и живой перевод** (LLM при `num_ctx` 2048) | ASR на GPU (GigaAM 2–2,5 ГБ) + qwen3.5:4b (3,4 + ~0,1 KV) ≈ 6,5 ГБ — **одновременно можно** | GigaAM на GPU + qwen3.5:4b ≈ 6,5 — впритык; надёжнее ASR на CPU | ASR на CPU, LLM 4B на GPU | ASR на CPU, перевод моделью 1,5–4B: медленно, проверить задержку |
| **После встречи: протокол и задачи** (16k) | По очереди: выгрузить ASR, затем qwen3.5:9b (≈7,6 ГБ с KV) или qwen3:8b/T-lite (≈8,5 ГБ с KV f16) | qwen3.5:4b, gemma4:e4b (если тег 6,6) или GigaChat3-10B-A1.8B (≈7,5) — по очереди | qwen3.5:4b (≈4,9 ГБ), phi4-mini | См. ниже |
| **Вопросы по встречам** (поиск + LLM) | Эмбеддинги на CPU (bge-m3 / Qwen3-Embedding-0.6B) + LLM на GPU | То же | То же | Эмбеддинги на CPU |

**Рекомендация для кода (`app/vram.py`, `app/hardware.py`).**
- Порог `high_vram` начинается с 10 ГБ и рекомендует qwen3:8b. На 10 ГБ это всего 27k контекста в f16, и места для ASR не остаётся.
- Если qwen3.5:9b выиграет у qwen3:8b на замерах, для 10 ГБ разумнее он: KV в 4,5 раза меньше.
- Анализ на 10 ГБ всегда запускать с выгрузкой ASR (`keep_alive: 0` уже есть в `app/vram.py`).

**MoE при частичной выгрузке (10 ГБ, эксперты на CPU).**
- В llama.cpp есть `--n-cpu-moe` / `-ot exps=CPU`: внимание и общие слои остаются на GPU, эксперты уходят в ОЗУ.
- На карте 12 ГБ Qwen3.5-35B-A3B даёт 17–34 ток/с в зависимости от числа выгруженных слоёв ([aiweekly](https://aiweekly.co/alerts/qwen3-moe-cpu-expert-offload-doubles-decode-speed-on-12gb-vram)). gpt-oss-20b со всеми экспертами на CPU занимал около 10 ГБ VRAM ([обсуждение llama.cpp](https://gh.r-mj.com/ggml-org/llama.cpp/discussions/15396)).
- **В Ollama такой настройки нет:** только `num_gpu` (число слоёв целиком). Поэтому MoE на 10 ГБ через Ollama будет заметно медленнее, чем через llama.cpp. Это надо замерить.
- Если MoE выиграет по качеству, придётся решать, переходить ли на llama-server (MIT).

**Только CPU.** Ryzen 7 7700X с DDR5-6000: Qwen3.5 4B Q4_K_M ≈ 24 ток/с, 8B ≈ 13 ток/с ([bestllmfor](https://bestllmfor.com/guide/llm-local-cpu-sans-gpu/), вторично). Но для протокола важнее **скорость чтения промпта (prefill)**: 16k токенов на CPU при 50–150 ток/с — это 2–5 минут ожидания (оценка). Её нужно мерить первой.
- Лучшие кандидаты для CPU — MoE с малым числом активных параметров:
  - GigaChat3-10B-A1.8B: 1,8B активных, ≈7 ГБ ОЗУ;
  - gpt-oss-20b: ≈14 ГБ ОЗУ;
  - Qwen3.6-35B-A3B: ≈22 ГБ ОЗУ.

### 2.4 Кандидаты LLM: качество на русском, скорость, JSON

**Structured output.** Ollama ограничивает ответ JSON-схемой через параметр `format`, это работает для любой модели ([docs Ollama](https://docs.ollama.com/capabilities/structured-outputs), [блог](https://registry.ollama.ai/blog/structured-outputs)). Семантику схема не гарантирует. С «думающими» моделями (Qwen3 thinking, gpt-oss с форматом harmony) нужно проверить, что `format` и отключение размышлений работают вместе (не проверено).

**Скорость на 3080** — оценка: генерация упирается в пропускную способность памяти (760 ГБ/с), примерно 0,6–0,7 × 760 / размер весов. Единственная найденная цифра — qwen3 8B Q4_K_M ≈ 89,5 ток/с ([llmrun.dev](https://llmrun.dev/gpu/rtx-3080-10gb?models-page=2), методика не указана). Для Llama 3.1 8B — 56–70 ток/с ([mustafa.net](https://mustafa.net/can-rtx-3080-run-llama-3-8b/)). Ядра Gated DeltaNet в llama.cpp могут работать медленнее обычного внимания — не проверено.

| Модель | Русский: данные | 3080, ток/с (оценка) | Чем может быть лучше | Приоритет |
|---|---|---|---|---|
| **qwen3.5:4b** (база) | Наш замер: на 3 русских записях не хуже 8–14B (`bench-report/report.md`) | ≈100–130 | — (база сравнения для 6–8 ГБ) | база |
| **qwen3.5:9b** | Наш замер: преимуществ над 4B на 3 коротких записях нет. Выборка мала | ≈65–80 | Малый KV: 77k контекста на 10 ГБ. Кандидат вместо qwen3:8b для 10 ГБ | **высокий** |
| **GigaChat3-10B-A1.8B** / 3.1 | MMLU_RU 5-shot 0,683 против 0,597 у Qwen3-4B-2507; RuBQ 0,65 против 0,32. Но BBH, GPQA, MATH хуже Qwen3-4B ([GH README](https://github.com/salute-developers/gigachat3)) | ≈120+ на GPU (1,8B активных); на CPU лучший кандидат | Обучена с нуля на русском корпусе, MIT, MLA (малый KV), быстрая на CPU. Проверить поддержку архитектуры в Ollama: GGUF есть, а движок Ollama — не проверено | **высокий** |
| **T-lite-it-2.1** (Qwen3-8B + русское дообучение) | Карточка: заметный рост на Ru Arena Hard относительно 1.0 ([зеркало карточки](https://huggingface-proxy.pages.dev/t-tech/T-lite-it-2.1)); у 1.0 на Ru Arena General 84,98 ([Space](https://vikhrmodels-arenahardlb.hf.space)) | ≈80–90 (как qwen3:8b) | Тот же размер и KV, что у qwen3:8b, лучше русский текст. Сравнение «яблоко к яблоку» с qwen3:8b. Официальный GGUF: t-tech/T-lite-it-2.1-GGUF | **высокий** |
| **gemma4:e4b** | Анекдотически: «отличный русский» с русским системным промптом, без него отвечает по-английски ([dev.to](https://dev.to/desve/gemma-4-e4b-on-mac-mini-m2-real-benchmarks-for-a-companion-robot-39pm)). MMMLU 76,6% ([aman.ai](https://aman.ai/primers/ai/gemma-4/)) | не проверено | Малый KV, Apache-2.0, другая семья моделей (снижает риск «всё на Qwen») | **высокий** |
| **QVikhr-3-4B-Instruction** | Ru Arena General 78,2 против 64,8 у Qwen3-4B ([featherless](https://featherless.ai/models/Vikhrmodels/QVikhr-3-4B-Instruction/readme)) | ≈130 | Русское дообучение 4B для 6 ГБ. Но архитектура Qwen3 (KV 144 КиБ) хуже Qwen3.5 по памяти | средний |
| **gpt-oss-20b** | Русский явно не заявлен ([Azure](https://ai.azure.com/catalog/models/gpt-oss-20b)) | 129 ток/с на 16 ГБ без выгрузки ([glukhov](https://www.glukhov.org/llm-performance/benchmarks/qwen3-30b-vs-gpt-oss-20b/)); на 10 ГБ меньше | Сильные рассуждения и structured outputs; ≈14 ГБ ОЗУ — вариант для CPU с 32 ГБ | средний |
| **qwen3.6:35b-a3b** | MERA: 0,792, 9-е место ([MERA](https://mera.a-ai.ru/en/news/Reasoning,%20Text)) | 17–34 при выгрузке экспертов на 12 ГБ (для 3.5-35B-A3B) | Лучшее качество из того, что запускается на 10 ГБ с выгрузкой и ≥32 ГБ ОЗУ. Для «режима качества» без спешки | средний |
| **ministral-3:8b** | Русских данных нет | ≈80 | Apache, другая семья. Но KV большой: на 8 ГБ всего 7k контекста | низкий |
| **phi4-mini** | ru есть в языках карточки, но карточка предупреждает о разном качестве ([HF через поиск](https://huggingface.co/microsoft/Phi-4-mini-instruct/blob/main/README.md)). В тесте выше уступил Gemma 4 E4B | ≈130 | MIT, мала. Запасной вариант для 6 ГБ | низкий |
| qwen3.5:2b / gemma4:e2b | — | — | Профиль «только CPU, мало ОЗУ» и живой перевод | низкий |
| Llama 3.x, Gemma 3, YandexGPT-5-Lite, Ministral-8B-2410 | — | — | Не подходят по лицензии | — |
| SmolLM3 | Русского нет | — | — | отклонить |

**Русские бенчмарки, которые стоит смотреть:**
- [MERA](https://mera.a-ai.ru/) — есть MERA Text 2.0 и MERA Reason;
- [Ru Arena General](https://vikhrmodels-arenahardlb.hf.space) — открывается только снимок без даты.

Бенчмарков именно на саммари встреч на русском я не нашёл, поэтому нужен свой замер (раздел 4).

### 2.5 Эмбеддинги и реранкеры (лёгкие)

Сейчас используется bge-m3 через Ollama: 568M параметров, MIT. Он же нужен для подсказок реранкеру.

| Модель | Лицензия | Размер | ru | ONNX / Ollama | Чем лучше | Приоритет |
|---|---|---|---|---|---|---|
| **Qwen3-Embedding-0.6B** | Apache-2.0 ([блог Qwen](https://qwenlm.github.io/blog/qwen3-embedding), [arXiv](https://arxiv.org/pdf/2506.05176v1)) | 0,6B | да (мультиязычная) | Ollama-тег — не проверено; ONNX — сторонние | MTEB multilingual ≈64,3 (вторично, [Accenture](https://sdk.airefinery.accenture.com/distiller/model_catalog/Embedding/Qwen/Qwen3-Embedding-0.6B/)). Поддерживает инструкции | **высокий** |
| **deepvk/USER-bge-m3** | Apache-2.0 ([HF через поиск](https://huggingface.co/deepvk/USER-bge-m3)) | как bge-m3 | дообучена под ru | Ollama — через GGUF/ONNX, не проверено | Та же архитектура, что сейчас, но под русский: самая дешёвая замена | **высокий** |
| ibm granite-embedding-278m-multilingual / R2 311M | Apache-2.0 ([GH repo](https://github.com/ibm-granite/granite-embedding-models/), [arXiv](https://arxiv.org/html/2502.20204v1)) | 278–311M | 12 языков; есть ли ru — не проверено | — | Вдвое легче bge-m3 | средний |
| intfloat/multilingual-e5-small | MIT — не проверено | 118M | да | ONNX есть (не проверено) | Самая лёгкая для CPU | средний |
| ai-forever/FRIDA, ai-sage/Giga-Embeddings-instruct | не проверено | 0,8B / ~3B | да, лидеры ruMTEB | — | Не лёгкие | низкий |
| embeddinggemma-300m | Gemma License ([вторично](https://freeapihub.com/ai-models/embeddinggemma)) | 300M | — | — | ❌ лицензия | — |
| **Qwen3-Reranker-0.6B** | Apache-2.0 ([блог](https://qwenlm.github.io/blog/qwen3-embedding)) | 0,6B | да | Ollama реранкеры не поддерживает: нужен onnxruntime или transformers (не проверено) | MTEB-R 65,8 | средний |
| BAAI/bge-reranker-v2-m3 | Apache-2.0 (вторично, [developersdigest](https://www.developersdigest.tech/models/rerankers/baai)) | 568M | мультиязычная | ONNX — сторонние | Пара к bge-m3 | средний |

---

## 3. Остальные направления (коротко)

### 3.1 ASR офлайн (ru/en)

| Кандидат | Лицензия | Размер | ru | ONNX / CT2 | Чем может быть лучше | Как мерить | Приоритет |
|---|---|---|---|---|---|---|---|
| **GigaAM-v3 e2e_rnnt / e2e_ctc** | MIT **[GH]** | 220M | да | ONNX (`to_onnx`, onnx-asr поддерживает E2E) **[GH]** | Пунктуация и нормализация в самой модели. Замерен ли именно e2e — проверить | WER и пунктуационный F1 на русских встречах | высокий (если ещё не e2e) |
| **Qwen3-ASR-0.6B / 1.7B** | Apache-2.0 **[GH LICENSE]** | 0,6 / 1,7B | да (из 30 языков) **[GH README]** | нет (vLLM / transformers) | Мультиязычность, определение языка, режим стриминга | WER ru/en на FLEURS и на встречах, VRAM | средний |
| **VibeVoice-ASR** (Microsoft) | MIT **[GH LICENSE]** | ≈7–9B | 50+ языков; ru — не проверено | нет | ASR, диаризация и таймкоды одним проходом до 60 минут ([arXiv](https://www.arxiv.org/pdf/2601.18184)) | WER и DER на встречах. Помещается только в 24 ГБ | низкий (не для 10 ГБ) |
| Omnilingual ASR CTC 1B (Meta) | Apache-2.0 **[GH LICENSE]** | 1B+ | да | — | 1600 языков | WER ru | низкий |
| Cohere Transcribe | Apache-2.0 ([HF-блог](https://huggingface.co/blog/CohereLabs/cohere-transcribe-03-2026-release)) | 2B | **нет** (14 языков) | — | Только для en | WER en | низкий |
| Voxtral Mini 4B Realtime | Apache-2.0 ([Simon Willison](https://simonwillison.net/2026/Feb/4/voxtral-2/)) | 4B | не проверено | — | Стриминг ~480 мс | — | низкий |

### 3.2 Стриминговый ASR (живые субтитры)

| Кандидат | Лицензия | ru | Формат | Заметки | Приоритет |
|---|---|---|---|---|---|
| **Nemotron 3.5 ASR streaming 0.6B** | NVIDIA Open Model License **или** OpenMDW-1.1 — источники расходятся ([letsdatascience](https://letsdatascience.com/news/nvidia-releases-open-nemotron-35-audio-transcription-and-tra-e4112b2f)) | 40 локалей; ru не проверено | NeMo; Vibe его уже поддерживает | Наследник Parakeet со стримингом. Лицензию надо проверить: NVIDIA OML — не из списка MIT/Apache/CC-BY, решать автору | средний |
| **Vosk small-streaming-ru** (Zipformer2) | Apache-2.0 ([HF через поиск](https://huggingface.co/alphacep/vosk-model-small-streaming-ru/blob/main/README.md)); код Vosk — Apache-2.0 **[GH]** | да | onnx-asr поддерживает Vosk 0.52+ **[GH]**, sherpa-onnx (Apache **[GH]**) | Common Voice ru WER 13,7 (по другой версии карточки 19,3). Лёгкая для CPU | средний |
| Qwen3-ASR streaming | Apache-2.0 | да | vLLM | На Windows vLLM — проблема | низкий |
| T-one | — | — | — | Уже замерен; onnx-asr пока не поддерживает его стриминг **[GH]** | — |

### 3.3 Диаризация

| Кандидат | Лицензия | ONNX | Заметки | Приоритет |
|---|---|---|---|---|
| **pyannote community-1** | CC-BY-4.0, доступ после согласия на HF ([карточка через поиск](https://huggingface.co/pyannote/speaker-diarization-community-1)) | Сегментация — да (pyannote-onnx, sherpa-onnx) | Уже в планах. Стандарт у конкурентов (WhisperX) | **высокий** |
| **Nemotron 3 Diarization** (100M, до 8 спикеров, стриминг и офлайн, 23.09.2026) | OpenMDW-1.1, «можно в коммерции»; превью-чекпойнт — только для оценки ([unite.ai](https://www.unite.ai/nvidia-releases-nemotron-3-diarization-open-weight-speaker-model/), [runtimewire](https://runtimewire.com/article/nvidia-nemotron-diarization-eight-speakers-open-weights)) | есть NeMo-Speech.cpp | Самое свежее end-to-end решение. Проверить карточку и текст OpenMDW | **высокий** |
| Streaming Sortformer 4spk v2.1 | NVIDIA Open Model License ([HF через поиск](https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2.1)) | сторонние ONNX | Не более 4 спикеров. Лицензия не из списка | низкий |
| DiariZen | Код MIT **[GH]**, веса **CC-BY-NC-4.0** ([HF через поиск](https://hug-proxy.pages.dev/BUT-FIT/diarizen-wavlm-large-s80-md)) | — | ❌ веса | — |
| 3D-Speaker (CAM++, ERes2NetV2) + кластеризация | Код Apache-2.0 **[GH]**; лицензия весов на ModelScope не проверена | sherpa-onnx | Основные веса обучены на китайском (zh-cn, 200k спикеров) **[GH]** | средний |
| NeMo MSDD / TitaNet | TitaNet — CC-BY-4.0 (не проверено в этой сессии) | — | Стек whisper-diarization | низкий |

### 3.4 Эмбеддинги голоса (узнавание людей между встречами)

| Кандидат | Лицензия | Размер | ONNX | Заметки | Приоритет |
|---|---|---|---|---|---|
| **WeSpeaker ResNet34-LM / ResNet293-LM (VoxCeleb)** | CC-BY-4.0, как у датасета **[GH docs/pretrained.md]** | 6,6M / 28M | официальные `.onnx` **[GH]** | ResNet34-LM используют pyannote и Vibe. ResNet293 точнее на VoxCeleb | **высокий** |
| **CAM++ (WeSpeaker VoxCeleb или 3D-Speaker en voxceleb)** | WeSpeaker: CC-BY-4.0 **[GH]**; 3D-Speaker — веса не проверены | 7,2M | да | Выбор OpenWhispr (512-d) | средний |
| WeSpeaker SimAMResNet34 (VoxBlink2, мультиязычная) | Лицензия VoxBlink2 не проверена (возможно NC) | — | да **[GH]** | Мультиязычная подготовка полезна для ru | проверить лицензию |
| ECAPA (текущая) | Apache-2.0 | — | — | База сравнения | — |

### 3.5 Пунктуация и регистр

Почти не нужна: GigaAM-v3 e2e, Parakeet и Whisper сами расставляют пунктуацию. Нужна для T-one и стриминговых моделей (Vosk).
- **kontur-ai/sbert_punc_case_ru** — Apache-2.0 (вторично, [mixpeek](https://mixpeek.com/model/kontur-ai/sbert_punc_case_ru)), 426M, есть сторонний ONNX. Приоритет низкий.

### 3.6 Перевод

| Кандидат | Лицензия | Формат | Заметки | Приоритет |
|---|---|---|---|---|
| **MADLAD-400-3B-MT** | Apache-2.0 ([HF через поиск](https://huggingface.co/google/madlad400-3b-mt/raw/main/README.md)) | CTranslate2-сборки есть (сторонние) | Через CTranslate2 (уже в зависимостях) быстрее LLM. 3B в int8 ≈3 ГБ | средний |
| opus-mt-ru-en / en-ru | CC-BY-4.0 — не проверено | CT2 | Очень лёгкие (~300 МБ), для живого перевода на CPU | средний |
| NLLB-200 | CC-BY-NC | — | ❌ (уже отмечено в `docs/dubbing.md`) | — |
| Специализированные LLM (Hunyuan-MT, Tower+, Aya, TranslateGemma) | По памяти: ограничения по регионам или NC; у TranslateGemma условия Gemma 3 | — | Не проверено. Через LLM общего назначения (Qwen3.5 и Gemma 4) — основной путь | — |

### 3.7 Шумоподавление, эхо, разделение речи

| Кандидат | Лицензия | Заметки | Приоритет |
|---|---|---|---|
| **GTCRN** | MIT **[GH LICENSE]** | Сверхлёгкий (≈50k параметров), есть ONNX, работает в реальном времени на CPU. Сравнить с DeepFilterNet3 | средний |
| **ClearerVoice-Studio: MossFormer2_SE_48K, MossFormer2_SS_16K (разделение)** | Код Apache-2.0 **[GH LICENSE]**; веса SE — Apache (вторично), SS — не проверено | Разделение наложенной речи — новая функция | средний (SE) / низкий (SS) |
| SpeexDSP AEC | BSD-подобная **[GH COPYING]** | Классическое подавление эха как эталон для своего GCC-PHAT + NLMS | низкий |
| WebRTC AEC3 | BSD (по памяти; Python-обёртки не проверены) | Самый практичный AEC | средний |

### 3.8 Определение языка

| Кандидат | Лицензия | Заметки | Приоритет |
|---|---|---|---|
| **speechbrain/lang-id-voxlingua107-ecapa** | Apache-2.0 ([HF через поиск](https://huggingface.co/speechbrain/lang-id-voxlingua107-ecapa)) | Та же SpeechBrain, что у нас; 107 языков, ошибка 6,7% | средний |
| Whisper LID | MIT | Уже есть в программе | — |
| MMS-LID | CC-BY-NC | ❌ | — |

### 3.9 Выравнивание слов по времени

| Кандидат | Лицензия | ru | Заметки | Приоритет |
|---|---|---|---|---|
| **Qwen3-ForcedAligner-0.6B** | Apache-2.0 **[GH LICENSE]** | **да** (11 языков, включая Russian) **[GH README]** | До 5 минут аудио на вызов; автор заявляет точнее E2E-таймкодов | **высокий** |
| **CTC-выравнивание на GigaAM v3 CTC** (ru) и Parakeet/NeMo CTC (en) | MIT / CC-BY-4.0 | да | Модели уже в программе, новых весов не нужно | высокий |
| ctc-forced-aligner + MMS-300m | Код BSD-2 **[GH]**, веса **CC-BY-NC-4.0** ([HF через поиск](https://huggingface.co/MahmoudAshraf/mms-300m-1130-forced-aligner/blob/main/README.md)) | да | ❌ веса, как и torchaudio `MMS_FA` | — |
| wav2vec2 из WhisperX (ru — jonatasgrosman) | Apache-2.0 — не проверено | да | Классика | низкий |

---

## 4. План замеров для локальной сессии

### Шаг 1 (первый). Сравнение LLM для профилей 10 ГБ и 6–8 ГБ, плюс CPU

**Эмуляция профилей на 3090.** Лучше занять видеопамять заглушкой, чем ограничивать `num_gpu`. Например, отдельный процесс на torch выделяет `24 − N − 0,5` ГБ и держит их. Тогда Ollama сама решит, сколько слоёв поместить, как на настоящей карте.
- Для профиля «с ASR» добавить загруженный GigaAM на CUDA (+2–2,5 ГБ) или Whisper turbo (+2,2 ГБ).
- Профиль CPU: `CUDA_VISIBLE_DEVICES=-1` или `num_gpu: 0`.
- Отдельно прогнать llama.cpp `llama-server` с `--n-cpu-moe` для MoE-моделей.

**Модели по профилям:**
- **10 ГБ:** qwen3:8b (база), qwen3.5:9b, T-lite-it-2.1, gemma4:e4b, GigaChat3.1-10B-A1.8B; плюс qwen3.6:35b-a3b и gpt-oss:20b с выгрузкой экспертов.
- **8 ГБ:** qwen3.5:4b (база), gemma4:e4b, GigaChat3.1-10B-A1.8B, QVikhr-3-4B.
- **6 ГБ:** qwen3.5:4b, phi4-mini, gemma4:e2b, QVikhr-3-4B.
- **CPU:** qwen3.5:4b, GigaChat3.1-10B-A1.8B, gpt-oss:20b, qwen3.5:2b.

**Данные:**
- 6–10 настоящих записей из библиотеки владельца (копия папки данных, `VERBALIOX_DATA_DIR`): 3 русских по 30–60 минут (16–32k токенов), 2 английских, 1 смешанная. Короткие записи 52, 65, 68 оставить для преемственности с прошлым замером.
- Владелец вручную размечает эталон: список задач (кто, что, срок) и 5–10 ключевых решений на запись.

**Метрики** (`app/bench.py` расширить):
1. Доля «непроверенных» пунктов — уже есть. Сначала исправить её на английских записях, см. `report.md`.
2. Полнота и точность извлечения задач против эталона: совпадение исполнителя и сути.
3. Доля валидных JSON при `format` со схемой, плюс отсутствие `<think>`.
4. Выдуманные имена, даты и числа (сверка с транскриптом).
5. Скорость: prefill (ток/с), время до первого токена, генерация (ток/с), полное время протокола.
6. Пик видеопамяти и ОЗУ; сколько слоёв Ollama поместила на GPU (`ollama ps`).
7. Слепое попарное сравнение протоколов владельцем; можно дополнить судьёй qwen3.6:27b на 3090.

**Контекст:** 16k (как в программе) и 32k. На 32k — с `OLLAMA_KV_CACHE_TYPE=q8_0` и без него, чтобы проверить, стоит ли включать q8_0 в программе.

**Критерий:** модель по умолчанию для профиля должна давать полноту задач не хуже текущей и валидный JSON не реже 98% (порог условный, на усмотрение владельца). Укладываться по времени в разумное ожидание — тоже на усмотрение владельца, например до 60 с на GPU для часовой встречи. Без выхода за видеопамять профиля.

### Шаг 2. Эмбеддинги поиска (CPU)
- **Модели:** bge-m3 против USER-bge-m3, Qwen3-Embedding-0.6B и multilingual-e5-small; реранкер Qwen3-Reranker-0.6B — опционально.
- **Данные:** 50–100 вопросов владельца к его встречам с отмеченным правильным фрагментом.
- **Метрики:** Recall@5, MRR, время индексации часа записи на CPU, ОЗУ.

### Шаг 3. Диаризация и голосовые профили
- **Модели:** pyannote community-1 и Nemotron 3 Diarization против текущей ECAPA с кластеризацией. Эмбеддинги: WeSpeaker ResNet34-LM, ResNet293-LM и CAM++.
- **Данные:** 5 записей Teams с ручной разметкой спикеров, из них одна с наложениями.
- **Метрики:** DER (collar 0,25), JER, ошибка числа спикеров, EER и точность узнавания человека между встречами (5–10 человек, по 3+ записи на каждого), VRAM и время.

### Шаг 4. Выравнивание и прочее (по возможности)
- Qwen3-ForcedAligner-0.6B против CTC GigaAM: средняя ошибка границ слов на 50 вручную размеченных фразах.
- GTCRN против DeepFilterNet3: DNSMOS и WER после очистки.
- Vosk streaming ru против T-one: задержка и WER для живых субтитров.
- MADLAD-3B (CT2) против qwen3.5:4b на переводе: COMET или оценка владельца.

**Перед каждым шагом:** открыть карточки HF всех моделей с пометками [HF через поиск] и [вторично], сверить лицензию и записать коммит ревизии, как в `tts-candidates.md`.
