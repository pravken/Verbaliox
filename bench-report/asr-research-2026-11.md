# Модели распознавания речи для Verbaliox: конкуренты, кандидаты, план замера (ноябрь 2026)

Исследование без изменений в репозитории. Источники — README и исходный код конкурентов (клоны `--depth 1`
от 24.11.2026), карточки моделей на Hugging Face (HF API), PyPI. Ссылки — у каждого утверждения.

## 0. Главное за минуту

1. **Причина зависаний у нас скорее всего не в модели, а в схеме.** Сейчас живые субтитры раз в 1,2 с заново
   распознают окно до 20 с (`app/live.py`: `LIVE_STEP_SEC = 1.2`, `LIVE_WINDOW_SEC = 20.0`), то есть до ~16 с
   звука на каждую секунду, а ONNX Runtime по умолчанию держит потоки в **активном ожидании (spinning)**. У нас
   уже ограничено число потоков (`app/asr_onnx.py: cpu_threads()` — половина ядер, 2–8), но spinning не выключен,
   приоритет процесса не понижен, а очередь расшифровки берёт ещё столько же потоков. Конкуренты так не делают:
   - RealtimeSTT замерил: на 7 потоках выключение spinning сократило медиану на 5-секундном звуке с **662 мс до
     107 мс** (конкуренция пулов потоков), а связка «потоковая Nemotron для черновика + Parakeet один раз в конце
     фразы» названа «substantially better CPU streaming behavior than repeatedly retranscribing a growing audio
     buffer» ([README](https://github.com/KoljaB/RealtimeSTT/blob/master/README.md),
     [docs/engines/sherpa-onnx.md](https://github.com/KoljaB/RealtimeSTT/blob/master/docs/engines/sherpa-onnx.md)).
   - Meetily режет живой звук по VAD (Silero, redemption 500 мс) и распознаёт каждый кусок речи **один раз**
     (`frontend/src-tauri/src/audio/pipeline.rs`, `VAD_REDEMPTION_TIME_MS = 500`).
   - OpenWhispr ограничивает потоки: `min(4, 0.75 × ядер)` (`src/helpers/parakeetWsServer.js`, строка 44).
   - Handy держит модель в **отдельном процессе-воркере** (`src-tauri/src/engine_supervisor/supervisor.rs`).
2. **Для субтитров на CPU лучший кандидат — Nemotron 3.5 ASR Streaming 0.6B (int8, sherpa-onnx).** Модель
   «cache-aware», каждый кадр считается один раз; ru есть (FLEURS ru 9,2–10,8 % по карточке); лицензия OpenMDW-1.1
   — разрешительная (MIT-подобная + патентная оговорка). Её уже взяли RealtimeSTT, OpenWhispr, Vibe, Handy.
3. **Для точной расшифровки появились бесплатные «улучшенные Parakeet v3»:** **Parakeet Ultra** (Moondream,
   CC-BY-4.0, FLEURS-25 9,55 % против 11,62 % у v3; ru 5,21 против 5,91) — есть готовый ONNX в раскладке
   onnx-asr; **Orukeet** (CC-BY-SA-4.0, но в небольшом замере ru и de ухудшились). Для ru по-прежнему сильнее всех
   GigaAM v3 e2e (FLEURS ru 5,35 % у e2e-RNNT по замеру transcribe.cpp) и GigaAM Multilingual Large (только
   ru/kk/ky/uz/en, без пунктуации).
4. **Новая NVIDIA-модель Nemotron-Labs-Unified-ASR-0.6b** (27.10.2026, OpenMDW-1.1) лучше Parakeet v3 офлайн и
   лучше Nemotron 3.5 в потоке (ru 4,42 % офлайн), но потоковый режим «буферный» (левый контекст пересчитывается
   каждый шаг) и пока только NeMo (PyTorch) — для Windows-CPU сейчас не годится, следить.
5. **Нельзя или «решать автору»:** SenseVoice (собственная лицензия FunASR), Kroko Community (CC-BY-SA, коммерческие —
   платно), Gemma 3n (Gemma Terms), Moonshine неанглийские (не MIT), сам рантайм Moondream Photon (лицензия не
   найдена). Без русского: Cohere Transcribe, Granite Speech 4.x/5.0, Phi-4-multimodal (аудио), Fun-ASR-MLT-Nano,
   Kyutai STT (en/fr), Voxtral Mini 3B, Canary-180m-flash, Moonshine streaming (en).

---

## 1. Конкуренты: что внутри и как они борются с нагрузкой

| Проект (лицензия) | Распознавание | VAD / потоковость | Диаризация | Приёмы против нагрузки |
|---|---|---|---|---|
| **Meetily** (MIT) | whisper.cpp (Windows — Vulkan, нужен AVX2) или **Parakeet v3 int8** ONNX от istupakov, через Rust `ort` | Silero (silero-rs), куски по паузам, redemption 500 мс в живом режиме, 2000 мс в пакетном | только в PRO («Speaker Identification») | int8 по умолчанию; потоки ORT не задаются (`ParakeetModel::new` → `intra_threads: None`) |
| **Hyprnote → anarlog** (MIT; enterprise — коммерческая) | whisper.cpp **q8_0** (`ggml-large-v3-turbo-q8_0.bin` и др.), на Mac — Argmax ParakeetKit/WhisperKit (нужен ключ), Soniqo (Apple) | — | свой `pyannote-local` (скользящая сегментация 10 с + эмбеддинги + агломеративная кластеризация) или pyannoteAI облако | — |
| **Scriberr** (MIT) | WhisperX, **NVIDIA Parakeet и Canary через NeMo** (PyTorch-окружение) | VAD WhisperX | pyannote | отдельные Docker-образы CPU/CUDA |
| **Buzz** (MIT) | Whisper (openai-whisper, whisper.cpp с Vulkan, faster-whisper, HF Transformers) | — | «Speaker identification» | Vulkan даже на встроенных GPU |
| **Vibe** (MIT) | собственные Rust-обёртки ggml: whisper, **Parakeet v3 GGUF (Q4_K_M)**, **Nemotron 3.5** | Silero v6.2 (ggml) | **NVIDIA Nemotron-3-Diarization Q8_0 GGUF** (до 8 говорящих; раньше — pyannote seg-3.0 + WeSpeaker CAM++, затем Sortformer) | GPU через Vulkan/CoreML |
| **noScribe** (GPL-3.0) | faster-whisper (модели «precise»/«fast») | `vad_filter=True` | pyannote (community-1, папка `pyannote/`) | Whisper и pyannote в **отдельных процессах multiprocessing spawn**; потоки = 0,75 × ядер на Mac |
| **WhisperX** (BSD-2) | faster-whisper (batched) + wav2vec2 выравнивание | pyannote/Silero VAD | pyannote **speaker-diarization-community-1** (CC-BY-4.0, нужен HF-токен) | на CPU советует `--compute_type int8` |
| **Whisper-WebUI** (Apache-2.0) | faster-whisper / insanely-fast-whisper | Silero VAD | pyannote 3.1 | — |
| **Handy** (MIT) | **transcribe.cpp** (ggml): Parakeet Unified EN, **Nemotron 3.5**, Canary-180m-flash, Cohere Transcribe, Whisper, Parakeet v3, Qwen3-ASR-0.6B… | Silero (1 поток) | — | **отдельный процесс-воркер** с супервизором; CPU-воркер не регистрирует GPU |
| **OpenWhispr** (MIT) | whisper.cpp, **sherpa-onnx**: Parakeet v3 int8, **Orukeet int8** (рекомендуемая), Nemotron 3.5 / Nemotron EN streaming int8 (онлайн), Cohere Transcribe int8 | Silero | sherpa-onnx: **pyannote segmentation-3.0 + 3D-Speaker CAM++ zh_en advanced** | потоки `min(4, 0.75×CPU)`; онлайн — один поток распознавания |
| **VoiceInk** (GPL-3.0, macOS) | whisper.cpp, Parakeet через FluidAudio (CoreML), transcribe.cpp GGUF, SenseVoice | — | — | — |
| **Screenpipe** (source-available, коммерческое — по лицензии) | Whisper large-v3-turbo локально или Deepgram | — | есть | заявляет 5–20 % CPU |
| **Amical** (MIT) | whisper.cpp: Whisper и **Parakeet v3** (рекомендует для европейских языков) | Silero | — | Vulkan на Windows |
| **Speakr** (AGPL-3.0 / коммерческая) | WhisperX (самостоятельный хостинг) или облака | — | WhisperX/облако | — |
| **transcribe-anything** (MIT) | openai-whisper, insanely-fast-whisper, WhisperX, SenseVoice | VAD WhisperX | pyannote | изолированные окружения |
| **whisper_streaming** (MIT) | faster-whisper и др., LocalAgreement-2 | Silero VAC | — | README: рекомендован GPU |
| **SimulStreaming** (UFAL) | Whisper large-v3 + AlignAtt | Silero VAC | — | README: «GPU with at least 10G VRAM… CPU… too slow for real-time» |
| **WhisperLive** (MIT) | faster-whisper / TensorRT / **OpenVINO** | Silero | онлайн-кластеризация эмбеддингов pyannote | `OMP_NUM_THREADS` / `--omp_num_threads` |
| **WhisperLiveKit** (Apache-2.0) | SimulStreaming/LocalAgreement Whisper, Voxtral Realtime, Qwen3-ASR (vLLM, causal), Canary-1b-v2 | Silero | **Streaming Sortformer** (NeMo), Diart (не рекомендуется) | замеры только на H100 |
| **RealtimeSTT** (Apache-2.0) | faster-whisper (GPU), на CPU: **Nemotron 3.5 int8 (живой текст) + Parakeet v3 int8 / Orukeet (финал)** через sherpa-onnx; также Moonshine, Qwen3-ASR, Kroko, Omnilingual, transcribe.cpp | Silero / WebRTC | — | **spinning off**, 7 потоков, «tail-mode» (досчитывать только новый хвост) |
| **speaches** (MIT) | faster-whisper (OpenAI-совместимый сервер) | — | — | выгрузка модели при простое |
| **LiveCaptions (abb128)** (GPL-3.0, Linux) | april-asr (LSTM-transducer icefall), **только английский** | потоковая модель | — | — |
| **LiveCaptions-Translator** (MIT) | **встроенные «Живые субтитры» Windows 11** + API перевода | — | — | своей модели нет |
| **Meetscribe / millet** | WhisperX (+ опционально Parakeet ONNX, английский) | — | pyannote community-1; режим «dual-diarize»: микрофон и системный звук распознаются раздельно, «YOU» = микрофон | `--compute-type int8` |

Ссылки на README: [Meetily](https://github.com/Zackriya-Solutions/meeting-minutes/blob/main/README.md),
[Hyprnote/anarlog](https://github.com/fastrepl/hyprnote/blob/main/README.md),
[Scriberr](https://github.com/rishikanthc/Scriberr/blob/main/README.md),
[Buzz](https://github.com/chidiwilliams/buzz/blob/main/README.md),
[Vibe](https://github.com/thewh1teagle/vibe/blob/main/README.md),
[noScribe](https://github.com/kaixxx/noScribe/blob/main/README.md),
[WhisperX](https://github.com/m-bain/whisperX/blob/main/README.md),
[Whisper-WebUI](https://github.com/jhj0517/Whisper-WebUI/blob/master/README.md),
[Handy](https://github.com/cjpais/Handy/blob/main/README.md),
[OpenWhispr](https://github.com/OpenWhispr/openwhispr/blob/main/README.md),
[VoiceInk](https://github.com/Beingpax/VoiceInk/blob/main/README.md),
[Screenpipe](https://github.com/mediar-ai/screenpipe/blob/main/README.md),
[Amical](https://github.com/amicalhq/amical/blob/main/README.md),
[Speakr](https://github.com/murtaza-nasir/speakr/blob/master/README.md),
[transcribe-anything](https://github.com/zackees/transcribe-anything/blob/main/README.md),
[whisper_streaming](https://github.com/ufal/whisper_streaming/blob/main/README.md),
[SimulStreaming](https://github.com/ufal/SimulStreaming/blob/main/README.md),
[WhisperLive](https://github.com/collabora/WhisperLive/blob/main/README.md),
[WhisperLiveKit](https://github.com/QuentinFuxa/WhisperLiveKit/blob/main/README.md),
[RealtimeSTT](https://github.com/KoljaB/RealtimeSTT/blob/master/README.md),
[speaches](https://github.com/speaches-ai/speaches/blob/master/README.md),
[LiveCaptions](https://github.com/abb128/LiveCaptions/blob/main/README.md),
[LiveCaptions-Translator](https://github.com/SakiRinn/LiveCaptions-Translator/blob/master/README.md),
[meetscribe](https://github.com/pretyflaco/meetscribe/blob/main/README.md).

### 1.1 Подтверждения из исходного кода

- **Meetily**: модели Parakeet — `frontend/src-tauri/src/parakeet_engine/parakeet_engine.rs` (строки 107–136:
  `encoder-model.int8.onnx` 652 183 999 байт, источник `istupakov/parakeet-tdt-0.6b-v3-onnx`, ревизия `8f23f0c…`,
  `QuantizationType::Int8 // Default to int8 for best performance`); сессии ORT —
  `parakeet_engine/model.rs` (`GraphOptimizationLevel::Level3`, `with_parallel_execution(true)`, потоки только если
  заданы, а `new()` передаёт `None`); VAD — `audio/vad.rs` (`min_speech_time = 250 мс`, «Increased min_speech_time to
  prevent tiny 40ms fragments»), живой конвейер — `audio/pipeline.rs` («VAD-driven pipeline: segments dispatched per
  speech burst»; комментарий: при сплошной речи сегмент не закрывается — issue #756).
  Репозиторий: <https://github.com/Zackriya-Solutions/meeting-minutes>.
- **OpenWhispr**: `src/helpers/parakeetWsServer.js` — `INTRA_OP_THREADS = Math.max(1, Math.min(4, Math.floor(AVAILABLE_CPUS * 0.75)))`,
  офлайн `--num-work-threads=3`, онлайн `--num-work-threads=2 --loop-interval-ms=2`; реестр моделей
  `src/models/modelRegistryData.json` (архивы sherpa-onnx: `sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-560ms-int8-2026-06-11`,
  `sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8`, Orukeet, Cohere 14-lang int8); диаризация
  `src/helpers/diarization.js` + `src/constants/speakerDetection.json`
  (`3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx`, pyannote segmentation-3.0, до 8 говорящих).
  <https://github.com/OpenWhispr/openwhispr>
- **Handy**: `src-tauri/src/catalog/mod.rs` — рейтинг: 1) parakeet-unified-en-0.6b, 2) **nemotron-3.5-asr-streaming-0.6b**,
  3) canary-180m-flash, 4) cohere-transcribe-03-2026, 5) whisper-medium, …, 7) parakeet-tdt-0.6b-v3;
  `engine_supervisor/supervisor.rs` — «single owner of the transcribe.cpp worker process»; Silero VAD с `n_threads: 1`
  (`audio_toolkit/vad/silero.rs`). <https://github.com/cjpais/Handy>
- **Vibe**: `desktop/src/lib/config.ts` — диаризация `nemotron-3-diarization-Q8_0.gguf` («Mirrored … from
  nvidia/Nemotron-3-Diarization (OpenMDW 1.1)», «Q8_0 matches F32 segments»), VAD `ggml-silero-v6.2.0.bin`;
  крейты `server/crates/{nemotron-rs,parakeet-rs,nemotron-diarize-rs,whisper-rs,zipformer-rs}`.
  <https://github.com/thewh1teagle/vibe>
- **noScribe**: `noScribe/whisper_mp_worker.py` (faster-whisper, `cpu_threads`, `vad_filter=True`, `beam_size=5`),
  `noScribe/main.py:328–336` (потоки = `os.cpu_count()`, на Mac 0,75 × производительных ядер),
  `tests/test_worker_import_lightweight.py` («The diarization/whisper subprocesses (multiprocessing "spawn")»).
  <https://github.com/kaixxx/noScribe>
- **RealtimeSTT**: `RealtimeSTT/transcription_engines/nemotron_engine.py` (как создаётся `OnlineRecognizer.from_transducer`
  для Nemotron, `feature_dim=128`, язык потока через `stream.set_option("language", …)`), `nemotron_ort_streaming.py`
  (свой ORT-движок со «снимком» состояния для мгновенного черновика на паузе).
  <https://github.com/KoljaB/RealtimeSTT>

### 1.2 Проблемы пользователей и как их решали

- **Нагрузка потоков ONNX Runtime.** RealtimeSTT: в стоковом sherpa-onnx 1.13.4 энкодер, декодер и joiner NeMo
  делят одну настройку потоков, «their ONNX Runtime worker pools can spin while waiting for work. Those pools may
  compete for the same cores»; выключение spinning: 662 → 107 мс; рекомендуемая конфигурация (2026-09-18) —
  sherpa-onnx 1.13.8, 7 потоков, файл провайдера с `SessionConfig.session.intra_op.allow_spinning=0` и
  `SessionConfig.session.inter_op.allow_spinning=0`, передаётся как `provider="cpu:/abs/path/cpu-session.conf"`
  ([docs/engines/sherpa-onnx.md](https://github.com/KoljaB/RealtimeSTT/blob/master/docs/engines/sherpa-onnx.md)).
  Документация ORT подтверждает ключи `session.intra_op.allow_spinning` / `session.inter_op.allow_spinning`
  (по умолчанию включены) и `session.intra_op.spin_duration_us` для клиентских сценариев — по выдаче поиска
  ([threading](https://onnxruntime.ai/docs/performance/tune-performance/threading.html); сам сайт из песочницы
  недоступен, текст не перепроверен). Сторонний случай: проект Headroom выключил spinning, потому что прокси грузил
  ~100 % всех ядер ([коммит](https://upd.dev/chopratejas/headroom/commit/5c561bd)).
- **Нестабильность Parakeet через sherpa-onnx на Windows.** RealtimeSTT: «Native Windows can load and run both models…
  but the Parakeet binding produced intermittent empty authoritative results… native Windows Parakeet is not promoted»
  (тот же документ, раздел Platform support). Значит, Parakeet на Windows лучше оставлять на onnx-asr (как у нас), а
  sherpa-onnx брать для Nemotron — и проверить на ПК.
- **Память ORT.** По выдаче поиска: в отчёте о Parakeet на CPU-сервере арену памяти ORT пришлось выключить — с ней
  RSS рос на ~520 МБ за сессию; окно 60 с давало пик ~1,65 ГБ, 30 с — ~1,16 ГБ
  ([dev.to](https://dev.to/thebuciyo/i-replaced-whisper-with-parakeet-on-a-55month-cpu-server-here-is-what-actually-happened-2a0f);
  страница из песочницы недоступна, цифры не перепроверены).
- **Сплошная речь и VAD-сегменты.** Meetily: длинный redemption (2000 мс) при непрерывном звуке держит сегмент
  открытым бесконечно, поэтому в живом режиме 500 мс (комментарий в `audio/pipeline.rs`, issue #756).
- **GPU-сбои на Windows.** Handy просит загрузчик Vulkan пропускать неявные слои (оверлеи и захват экрана роняли
  процесс, [#2049](https://github.com/cjpais/Handy/issues/2049)); CPU-воркер вообще не инициализирует GPU.
- **Whisper в потоке на CPU слишком медленный.** SimulStreaming прямо пишет, что CPU «too slow for real-time»;
  в бенчмарке onnx-asr Whisper large-v3-turbo на CPU — RTFx 2,9–5,4
  ([benchmarks](https://github.com/istupakov/onnx-asr/blob/main/docs/benchmarks.md)).
- Поиск по issues Meetily/Handy с ключами «CPU 100 %», «freeze» явных совпадений не дал (поиск по GitHub API из
  песочницы закрыт, MCP-доступ только к репозиториям пользователя).

### 1.3 Кто какие модели берёт (сводка)

- **Parakeet v3**: Meetily (int8 ONNX istupakov, CPU), OpenWhispr (int8 sherpa-onnx, CPU), Amical (whisper.cpp),
  Vibe (GGUF Q4_K_M), Handy (GGUF через transcribe.cpp), RealtimeSTT (int8 sherpa-onnx как финальная модель),
  Scriberr (NeMo), Hyprnote (Argmax, Mac). Все десктопные — **int8 / Q8 / Q4 на CPU**, ни один не использует fp32.
  Результаты: onnx-asr int8 на 8 ядрах EPYC — 28× реального времени, sherpa-onnx int8 — 42×, ggml q8_0 — 45×
  ([parakeet-redux](https://huggingface.co/moondream/parakeet-redux), раздел Performance).
- **Nemotron 3.5 streaming**: RealtimeSTT (живой текст на CPU), OpenWhispr (онлайн), Handy (#2 в рейтинге), Vibe,
  NVIDIA NeMo-Speech.cpp (модель по умолчанию).
- **Moonshine**: RealtimeSTT (только en), transcribe.cpp. Для ru бесполезен.
- **Qwen3-ASR**: WhisperLiveKit (vLLM/causal, en), Handy (#9), RealtimeSTT.
- **whisper.cpp**: Hyprnote (q8_0, вплоть до large-v3-turbo-q8_0), Handy (ggml-small, medium-q4_1, large-v3-turbo,
  large-v3-q5_0), OpenWhispr (до turbo-q5_0), Meetily (Vulkan), Amical, Buzz.
- **Vosk**: среди проверенных проектов не встречен; поддерживается onnx-asr (`alphacep/vosk-model-ru`, Apache-2.0).
- **Русские проекты**: готового открытого десктопного приложения «GigaAM + диаризация для встреч» не найдено;
  есть серверные сборки (citeck-stt-sidecar: GigaAM кусками по 25 с + pyannote) и статьи на Хабре
  ([поиск](https://citeck-ecos.readthedocs.io/en/latest/general/AI_instruments/citeck-stt-sidecar.html),
  [habr](https://habr.com/ru/posts/992938)).

### 1.4 Диаризация у конкурентов

| Подход | Кто | Лицензия модели |
|---|---|---|
| pyannote speaker-diarization-community-1 | WhisperX, noScribe, Meetscribe, transcribe-anything | CC-BY-4.0, HF-гейт (нужен токен) — [HF](https://huggingface.co/pyannote/speaker-diarization-community-1) |
| pyannote segmentation-3.0 + 3D-Speaker CAM++ (ONNX, sherpa-onnx) | OpenWhispr | seg-3.0 MIT; CAM++ из 3D-Speaker (Apache-2.0 — по репозиторию 3D-Speaker, не перепроверено) |
| NVIDIA **Nemotron-3-Diarization** (до 8 говорящих, поток и офлайн) | Vibe (GGUF Q8_0), NeMo-Speech.cpp | **OpenMDW-1.1** — [HF](https://huggingface.co/nvidia/Nemotron-3-Diarization) |
| Streaming Sortformer 4spk v2/v2.1 | WhisperLiveKit, transcribe.cpp (DER 14,73 % на AMI IHM, Q8 139 МБ) | NVIDIA Open Model License |
| своя кластеризация эмбеддингов | Hyprnote (`crates/pyannote-local`), WhisperLive (онлайн, cosine) | — |
| раздельные каналы микрофон/система | Meetscribe («dual-diarize»: свой голос = YOU) | — |

Для Verbaliox (ECAPA + Nemotron diar уже есть) прямой «апгрейд» — Nemotron-3-Diarization, если нынешний «Nemotron
diar» — Sortformer: лицензия OpenMDW лучше NVIDIA OML, и до 8 говорящих вместо 4. Приём Meetscribe —
бесплатная разметка «я / собеседники» по каналу микрофона.

---

## 2. Модели: проверка

Обозначения лицензии: **можно** — коммерческое использование прямо разрешено; **можно, с условиями** — атрибуция,
копия лицензии, share-alike; **решать автору** — нестандартные условия или неясности; **нельзя**.

### 2.1 Кандидаты для субтитров (CPU, потоково)

**Nemotron 3.5 ASR Streaming 0.6B** — <https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b>
- Лицензия: **OpenMDW-1.1 — можно, с условиями**: «permission… to deal in the Model Materials without restriction»,
  при распространении приложить текст соглашения и уведомления; права прекращаются при патентном иске; на выходы
  ограничений нет ([текст](https://github.com/OpenMDW/OpenMDW/blob/main/1.1/LICENSE.OpenMDW-1.1)). Карточка: «ready
  for commercial use».
- 600M параметров, Cache-Aware FastConformer-RNNT, чанки 80/160/320/560/1120 мс, пунктуация и регистр, языковой
  промпт или `auto` (добавляет тег языка). 40 локалей; «transcription-ready» 19 — среди них **ru-RU, en, de, fr, es,
  it, pt, nl, uk**; pl/cs/sv и др. — «broad coverage»; el/lt/lv/sl — требуют дообучения.
- FLEURS WER, ru: 10,84 (80 мс) / 10,73 / 9,87 / **9,60 (560 мс)** / 9,17 (1,12 с) с указанием языка; с автоопределением
  12,47…10,03. de: 9,81…8,31; en: 9,43…7,91 (таблица Performance в карточке). Замер transcribe.cpp (Q8_0): ru 12,61 %,
  de 10,33 % ([docs](https://github.com/handy-computer/transcribe.cpp/blob/main/docs/models/nemotron-3.5-asr-streaming-0.6b.md)).
- Файлы: sherpa-onnx int8 архив 475 МБ (≈650 МБ распакованный, по OpenWhispr) —
  `https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-560ms-int8-2026-06-11.tar.bz2`
  (есть также 160ms и 1120ms; размеры проверены HEAD-запросом). GGUF: F32 2,55 ГБ, Q8_0 751 МБ, Q4_K_M 496 МБ.
- Скорость CPU: NVIDIA NeMo-Speech.cpp, i7-11700K, 8 потоков, чанк 160 мс (английская Nemotron той же архитектуры,
  Q8_0): **27 мс на чанк, 5,6× реального времени** ([BENCHMARK.md](https://github.com/NVIDIA/NeMo-Speech.cpp/blob/main/BENCHMARK.md)).
  При чанке 560 мс накладные расходы на чанк меньше. Для sherpa-onnx int8 опубликованных RTFx нет — замерить.
- Рантаймы на Windows: **sherpa-onnx 2.0.3** (Apache-2.0, колёса для Windows на PyPI, 22.11.2026);
  transcribe.cpp (MIT; Python-обёртка 0.4.2 «in development», нужна своя сборка `libtranscribe`);
  NeMo-Speech.cpp (Apache-2.0, готовые сборки для Windows, CLI и локальный сервер с OpenAI-совместимым API и
  WebSocket; Python-обёртки нет — только C SDK/HTTP). onnx-asr Nemotron **не поддерживает**.
- ONNX-сборки сообщества: `onnx-community/nemotron-3.5-asr-streaming-0.6b-onnx-int4` — в метаданных противоречие
  (`license: mit`, `license_name: nvidia-open-model-license` при OpenMDW у оригинала) — лучше не брать.

**Parakeet TDT 0.6B v3** (текущая) — <https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3>
- CC-BY-4.0 — **можно, с условиями** (атрибуция). 25 европейских языков с ru и uk. FLEURS ru 5,51, de 5,04, en 4,85;
  CoVoST2 ru 3,0 (model-index карточки). Не потоковая (офлайн TDT).
- onnx-asr CPU (Ryzen 9800X3D): fp32 RTFx 33,4, int8 30,5 — на этом процессоре int8 не быстрее; GPU RTX 5070 Ti CUDA 74,8,
  TensorRT fp16 278,6 ([benchmarks](https://github.com/istupakov/onnx-asr/blob/main/docs/benchmarks.md)).
  int8 энкодер 652 МБ против ~2,4 ГБ fp32 — экономия памяти ~1,8 ГБ.

**T-one** (T-Tech) — <https://huggingface.co/t-tech/T-one>
- Apache-2.0 — **можно**. Только ru, 71M, потоковый Conformer-CTC, чанки 300 мс, телефония. WER: call-center 8,63,
  CommonVoice 19 — 5,32 (GigaAM-RNNT v2 — 2,68), OpenSTT calls 20,27. Без пунктуации (CTC + опциональный KenLM).
- sherpa-onnx: `OnlineRecognizer.from_t_one_ctc`, архив `sherpa-onnx-streaming-t-one-russian-2025-09-08` 128 МБ
  ([пример](https://github.com/k2-fsa/sherpa-onnx/blob/master/python-api-examples/online-t-one-ctc-decode-files.py));
  onnx-asr — только непотоково. onnx-asr CPU RTFx 26,3.
- По таблице GigaAM v3 «T-One + LM» заметно хуже на нетелефонных доменах (Open Datasets 5,7 против 2,6 у V3_RNNT).

**GigaAM v3** (Сбер) — <https://huggingface.co/ai-sage/GigaAM-v3>
- MIT — **можно**. ru (и немного en), 220–240M; e2e-варианты дают пунктуацию и нормализацию. Средний WER по доменам:
  V3_RNNT 8,4, V3_CTC 9,2, T-One+LM 19,4, Whisper 25,1. FLEURS ru (transcribe.cpp, Q8_0): e2e-rnnt 5,35, e2e-ctc 5,53.
- Непотоковая, но очень быстрая: onnx-asr CPU int8 e2e-ctc RTFx 52, e2e-rnnt 42,5. Для субтитров — короткие VAD-фразы.

**Moonshine Streaming** — MIT, но только en ([HF](https://huggingface.co/moonshine-ai/moonshine-streaming-medium));
неанглийские Moonshine — лицензия «other» (не MIT). **Не подходит.**

**Voxtral Mini 4B Realtime 2602** — <https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602>
- Apache-2.0 — **можно**. 13 языков с ru; FLEURS ru 6,02 % при задержке 480 мс (5,56 при 960 мс), de 6,19, en 4,90.
- 4B, BF16; рекомендован vLLM (на Windows нет). GGUF Q4_K_M 2,83 ГБ (transcribe.cpp); даже на Apple Metal ~7×
  реального времени — для CPU-субтитров тяжело. Вариант для GPU-субтитров на RTX 3080 через transcribe.cpp/Vulkan —
  проверить отдельно.

**Nemotron-Labs-Unified-ASR-0.6b** — <https://huggingface.co/nvidia/nemotron-labs-unified-asr-0.6b>
- OpenMDW-1.1 — **можно, с условиями**. 25 европейских языков. Офлайн ru 4,42 %, поток 1,12 с — 5,69, 0,56 с — 6,70,
  0,16 с — 11,71 (среднее по FLEURS/MCV/MLS). Сравнение по 25 языкам: офлайн 9,49 против 10,55 у Parakeet v3;
  поток 1,12 с 11,85 против 20,00 у Nemotron 3.5.
- Ограничения: «The current streaming inference pipeline is buffered, not cache-aware: the left context is recomputed
  at every chunk step» (левый контекст 5,6 с) — на CPU дороже Nemotron 3.5; рантайм только NeMo 3.1. ONNX/GGUF пока нет
  (по поиску HF). **Следить; для офлайн-расшифровки — кандидат №1, когда появится ONNX.**

### 2.2 Кандидаты для расшифровки (точность)

**Parakeet Ultra** (Moondream) — <https://huggingface.co/moondream/parakeet-ultra>
- CC-BY-4.0 — **можно, с условиями**. Дообученная Parakeet v3, та же архитектура/токенизатор/языки.
  Open ASR (7 англ. наборов) 5,80 против 6,26; FLEURS-25 **9,55 против 11,62**; шум 5,82 против 6,72; TED-LIUM 1,94
  против 2,71. FLEURS ru **5,21 против 5,91**, uk 4,75 против 5,94. transcribe.cpp Q8_0: ru 5,63 (v3 — 6,54).
- ONNX в раскладке onnx-asr (сообщество): `Masterx/parakeet-tdt-0.6b-ultra-onnx` — графы istupakov v3 с подменой весов,
  int8 по тому же рецепту, fp16, fp32; «loads in onnx-asr… unchanged»
  ([HF](https://huggingface.co/Masterx/parakeet-tdt-0.6b-ultra-onnx)); альтернатива —
  `Olicorne/parakeet-tdt-0.6b-v3-ultra-onnx` (int8 MatMulNBits, w4a8 383 МБ). Это сторонние экспорты (сотни скачиваний) —
  сверить вывод с GGUF transcribe.cpp на нескольких файлах.
- Родной рантайм Moondream Photon (`pip install moondream`): лицензия рантайма не найдена — **решать автору**, не брать.
- **Parakeet Redux** (тернарная, 178 МБ, 113× на 8 ядрах) — CC-BY-4.0, но ru хуже: 7,91 против 5,91 у v3; работает только
  в Photon. Не брать.

**Orukeet** (Oruk AI, Стэнфорд и др.) — <https://huggingface.co/oruk/orukeet>
- **CC-BY-SA-4.0 — можно, с условиями** (атрибуция + share-alike для производных весов; распространение без изменений —
  копия лицензии и NOTICE). FLEURS-25 9,85 против 11,01 у v3; LibriSpeech clean 1,46.
- Но независимый замер (30 клипов FLEURS en/de/es/fr/ru/uk): «German and Russian WER regressed in both engines»
  ([ysdede/orukeet-0.6b-onnx](https://huggingface.co/ysdede/orukeet-0.6b-onnx)) — для ru сомнительна. Есть ONNX int8
  в раскладке onnx-asr (тот же репозиторий). Скорость CPU: Meetily-движок 47,3× против 36,6× у v3.

**GigaAM v3 e2e-RNNT / e2e-CTC** — см. 2.1. Для ru — эталон точности на CPU.

**GigaAM Multilingual (Large)** — <https://huggingface.co/ai-sage/GigaAM-Multilingual>
- MIT — **можно**. 220M / 600M, CTC по символам (без пунктуации). ru FLEURS 3,0 (Large) / 4,4; CV 5,1; en FLEURS 9,4 (слабо);
  нет de/fr/… — только ru, en, kk, ky, uz. onnx-asr: `gigaam-multilingual-large-ctc`. Интересна как «самая точная ru»,
  но нужна отдельная пунктуация.

**Qwen3-ASR 0.6B / 1.7B** — <https://huggingface.co/Qwen/Qwen3-ASR-1.7B>
- Apache-2.0 — **можно**. 30 языков + 22 диалекта китайского, ru есть; LID. Среднее по FLEURS (12 языков с ru): 1.7B 4,90,
  0.6B 7,57, Whisper-large-v3 5,27; CommonVoice (13 языков с ru): 9,18 / 12,75 / 10,77. Потоковый режим — только vLLM
  (на Windows нет). Forced Aligner 0.6B даёт таймкоды, ru поддержан.
- Рантаймы: `qwen-asr` 0.0.6 (transformers; bf16 на GPU 1.7B ≈ 4–5 ГБ — оценка), sherpa-onnx int8 0.6B (архив 879 МБ,
  `OfflineRecognizer.from_qwen3_asr`), transcribe.cpp GGUF (0.6B Q8 850 МБ — «near-realtime CPU», то есть медленно).
  Для CPU-субтитров не годится; для GPU-расшифровки — кандидат.

**Canary-1b-v2** — <https://huggingface.co/nvidia/canary-1b-v2>
- CC-BY-4.0 — **можно, с условиями**. 25 европейских языков + перевод en↔X. FLEURS ru 6,9, de 4,4, en 4,5 — по ru хуже
  Parakeet v3 (5,51). onnx-asr CPU RTFx 7,7 (int8 14,4), RTX 28,7. Смысл — только если нужен встроенный перевод.

**Whisper large-v3 / large-v3-turbo** — MIT — **можно**. Текущий эталон; Qwen-таблица: Whisper-large-v3 FLEURS (12 яз.) 5,27.
onnx-asr CPU turbo RTFx 2,9–3,9. На GPU (faster-whisper/CTranslate2 4.9.1) остаётся рабочим вариантом.

**Nemotron 3.5 Transcribe 30B-A4B** — OpenMDW-1.1, 40 языков, лидер Open ASR (4,71 en, multilingual 4,62), но 34B
параметров (4,3B активных) — не для RTX 3080 10 ГБ. Только к сведению.

### 2.3 Прочие модели 2025–2026: вердикт кратко

| Модель | Лицензия | ru | Вердикт |
|---|---|---|---|
| Cohere Transcribe 03-2026 (2B) | Apache-2.0, HF-гейт | **нет** (14 языков: ar, de, el, en, es, fr, it, ja, ko, nl, pl, pt, vi, zh) | не подходит |
| IBM Granite Speech 4.0/4.1/5.0 | Apache-2.0 (у `…-turboctc-nc` суффикс nc — проверить) | **нет** (en, fr, de, es, pt, it/ja) | не подходит |
| Microsoft Phi-4-multimodal | MIT | аудио — **нет** (en, zh, de, fr, it, ja, es, pt) | не подходит |
| Meta Omnilingual ASR (300M–7B) | Apache-2.0 | да, но ru FLEURS 6,4 / CV 13,6 (1B LLM, по таблице GigaAM) | хуже GigaAM/Parakeet |
| Fun-ASR-MLT-Nano-2512 | Apache-2.0 | **нет** | не подходит |
| SenseVoice Small | FunASR Model License | нет | **решать автору / не брать** |
| FireRedASR2 | Apache-2.0 | нет (zh/en) | не подходит |
| Dolphin | Apache-2.0 | азиатские языки | не подходит |
| Kyutai STT 1B | CC-BY-4.0 | нет (en/fr) | не подходит |
| Voxtral Mini 3B 2507 | Apache-2.0 | нет в метаданных (en, fr, de, es, it, pt, nl, hi) | не подходит |
| Canary-180m-flash | CC-BY-4.0 | нет (en, de, es, fr) | не подходит |
| Kroko ASR | Community — CC-BY-SA, коммерческие — платно (по [RealtimeSTT licenses](https://github.com/KoljaB/RealtimeSTT/blob/master/docs/licenses.md)) | нет (en, fr, de, es, pt) | **решать автору / не брать** |
| Gemma 3n (аудио) | Gemma Terms of Use (HF-гейт) | — | **решать автору** |
| Parakeet Unified EN 0.6B, Multitalker Parakeet, Sortformer, Nemotron Speech Streaming EN | NVIDIA Open Model License | нет (en) / диаризация | можно, с условиями (текст NVIDIA OML из песочницы не открылся — не перепроверен) |
| Vosk ru 0.54 / small 0.52 | Apache-2.0 | да | можно; уступает GigaAM (см. таблицу T-one) |

Лидерборд HF Open ASR: данные (`hf-audio/open-asr-leaderboard-results`, `hf-audio/multilingual_evals`) закрыты (401),
мультиязычная вкладка покрывает fr, de, es, it, pt, hi, nl, hy, zh — **русского нет**
([init.py](https://huggingface.co/spaces/hf-audio/open_asr_leaderboard/blob/main/init.py)). Цифры лидерборда выше —
из карточек моделей, которые на него ссылаются.

### 2.4 Сводная таблица ru / de / en (FLEURS WER, %; источники выше)

| Модель | ru | de | en | Примечание |
|---|---|---|---|---|
| GigaAM Multilingual Large | 3,0 | — | 9,4 | без пунктуации |
| Whisper large-v3 | 3,1 | — | 3,9 | по карточке GigaAM Multilingual |
| Nemotron-Labs-Unified (офлайн) | 4,42* | 4,32* | 5,89* | *среднее FLEURS+MCV+MLS |
| Parakeet Ultra | 5,21 | — | — | 25 языков: 9,55 |
| GigaAM v3 e2e-RNNT | 5,35 | — | — | замер transcribe.cpp |
| Parakeet v3 | 5,51 | 5,04 | 4,85 | |
| Voxtral Realtime 480 мс | 6,02 | 6,19 | 4,90 | GPU |
| Canary-1b-v2 | 6,9 | 4,4 | 4,5 | |
| Nemotron 3.5 streaming 560 мс | 9,60 | 8,42 | 7,99 | с указанием языка |

(Нормализация текста у источников разная — сравнивать строго можно только на одном наборе, отсюда замер на ПК.)

---

## 3. Шортлист для замера на ПК пользователя

Общие условия замера: одинаковые файлы (ru, en, de; реальные встречи пользователя — только локально), одна и та же
нормализация WER; фиксировать RTFx, пик RAM, загрузку CPU и — главное для субтитров — **задержку отклика интерфейса**
(например, джиттер таймера 16 мс в отдельном потоке/процессе, пока идёт распознавание) при параллельной расшифровке.
Все рантаймы — в отдельном процессе с приоритетом «ниже среднего».

Общий шаблон ONNX Runtime (onnx-asr):

```python
import onnxruntime as ort
import onnx_asr  # 0.12.0

def cpu_options(threads: int) -> ort.SessionOptions:
    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    so.inter_op_num_threads = 1
    so.add_session_config_entry("session.intra_op.allow_spinning", "0")
    so.add_session_config_entry("session.inter_op.allow_spinning", "0")
    # so.enable_cpu_mem_arena = False   # вариант замера: рост RSS против скорости
    return so
```

### «Субтитры (CPU, потоково)»

| # | Модель | Где взять | Рантайм | Квантизация | RAM (оценка) |
|---|---|---|---|---|---|
| S1 | **Nemotron 3.5 ASR Streaming 0.6B**, чанк 560 мс (контроль: 160 и 1120 мс) | `github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-560ms-int8-2026-06-11.tar.bz2` (475 МБ) | `sherpa-onnx==2.0.3` (+`sherpa-onnx-core`) | int8 | ~1 ГБ |
| S2 | **Parakeet v3 int8, но по-другому**: распознаётся только текущая фраза по Silero VAD (≤ 6–8 с), финал — один раз | `istupakov/parakeet-tdt-0.6b-v3-onnx` (`encoder-model.int8.onnx` 652 МБ) | `onnx-asr==0.12.0`, `onnxruntime==1.32.0` | int8 | ~1–1,5 ГБ |
| S3 | **GigaAM v3 e2e-CTC** (ru), та же VAD-схема | `istupakov/gigaam-v3-onnx` | onnx-asr 0.12.0 | int8 | ~0,5 ГБ |
| S4 | **T-one** (ru, настоящий поток 300 мс, 71M) | `…/asr-models/sherpa-onnx-streaming-t-one-russian-2025-09-08.tar.bz2` (128 МБ) | sherpa-onnx 2.0.3 | fp32 | ~0,3 ГБ |

S1 — загрузка (параметры как в RealtimeSTT `nemotron_engine.py`; проверить, что в 2.0.3 сохранился синтаксис
`provider="cpu:<conf>"`, введённый в 1.13.8):

```python
import sherpa_onnx, numpy as np
d = r"C:\...\sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-560ms-int8-2026-06-11"
# cpu-session.conf: две строки
#   SessionConfig.session.intra_op.allow_spinning=0
#   SessionConfig.session.inter_op.allow_spinning=0
rec = sherpa_onnx.OnlineRecognizer.from_transducer(
    tokens=f"{d}\\tokens.txt", encoder=f"{d}\\encoder.int8.onnx",
    decoder=f"{d}\\decoder.int8.onnx", joiner=f"{d}\\joiner.int8.onnx",
    num_threads=2, sample_rate=16000, feature_dim=128,
    decoding_method="greedy_search", enable_endpoint_detection=True,
    provider=r"cpu:C:\...\cpu-session.conf")
s = rec.create_stream()
s.set_option("language", "ru-RU")          # или "auto": тег языка в конце фразы
for chunk in audio_chunks_16k_float32:     # только новые кадры
    s.accept_waveform(16000, chunk)
    while rec.is_ready(s):
        rec.decode_stream(s)
    text = rec.get_result(s)
    if rec.is_endpoint(s):
        rec.reset(s)                       # фраза закончена
```

Ожидаемое: нагрузка постоянная и не растёт с длиной фразы (каждый кадр — один раз). Рекомендованная архитектура,
как в RealtimeSTT: S1 — черновик на экране, а финальный текст фразы — один проход точной модели (Parakeet/Ultra
или GigaAM) по завершённой фразе.

S2/S3 — загрузка:

```python
vad = onnx_asr.load_vad("silero", sess_options=cpu_options(1))
asr = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3", r"C:\...\parakeet-v3",
                          quantization="int8", sess_options=cpu_options(2))
# GigaAM: onnx_asr.load_model("gigaam-v3-e2e-ctc", path, quantization="int8", sess_options=cpu_options(2))
# черновик: распознать только звук текущей фразы (с начала речи по VAD), не чаще 1 раза в 1–1,5 с;
# после паузы ≥ 500 мс фраза финальна и больше не пересчитывается.
```

S4 — `sherpa_onnx.OnlineRecognizer.from_t_one_ctc(...)` по
[примеру](https://github.com/k2-fsa/sherpa-onnx/blob/master/python-api-examples/online-t-one-ctc-decode-files.py);
вывод без пунктуации, модель телефонная — проверить качество на звуке Teams/Zoom.

### «Расшифровка (точность)»

| # | Модель | Где взять | Рантайм | Квантизация | RAM/VRAM (оценка) |
|---|---|---|---|---|---|
| T1 | **Parakeet Ultra** | `Masterx/parakeet-tdt-0.6b-ultra-onnx` (int8 652 МБ / fp16 1,24 ГБ / fp32 2,4 ГБ); сверка — `handy-computer/parakeet-ultra-gguf` | onnx-asr 0.12.0 (CPU, CUDA, TensorRT) | int8 на CPU, fp32/fp16 на GPU | CPU ~1,5 ГБ; GPU ~3 ГБ |
| T2 | **GigaAM v3 e2e-RNNT** (ru, эталон; уже есть) | `istupakov/gigaam-v3-onnx` | onnx-asr | fp32 / int8 | ~1 ГБ |
| T3 | **Qwen3-ASR-1.7B** (GPU) | `Qwen/Qwen3-ASR-1.7B` (+ `Qwen/Qwen3-ForcedAligner-0.6B` для таймкодов) | `qwen-asr==0.0.6` (transformers, torch CUDA) | bf16 | VRAM ~5–6 ГБ |
| T4 | **Canary-1b-v2** или Whisper large-v3-turbo (контроль, текущая) | `istupakov/canary-1b-v2-onnx`; faster-whisper `large-v3-turbo` | onnx-asr / faster-whisper 1.2.1 + ctranslate2 4.9.1 | int8 CPU, fp16 GPU | 2–4 ГБ |

T1:

```python
asr = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3", r"C:\...\parakeet-tdt-0.6b-ultra-onnx",
                          quantization="int8", sess_options=cpu_options(threads))   # CPU
# GPU: providers=["CUDAExecutionProvider"], quantization=None (fp32) или fp16-файлы
model = asr.with_vad(onnx_asr.load_vad("silero"), max_speech_duration_s=20).with_timestamps()
```

T3:

```python
import torch
from qwen_asr import Qwen3ASRModel
m = Qwen3ASRModel.from_pretrained("Qwen/Qwen3-ASR-1.7B", dtype=torch.bfloat16, device_map="cuda:0",
                                  max_inference_batch_size=8, max_new_tokens=256)
r = m.transcribe(audio=(wave_16k, 16000), language="Russian")   # None — автоопределение
```

(Пример из [карточки](https://huggingface.co/Qwen/Qwen3-ASR-1.7B); подавать VAD-сегменты ≤ 30 с; vLLM на Windows нет.)

Кандидаты «на потом» (появятся ONNX/Windows-рантайм — добавить в замер): Nemotron-Labs-Unified-ASR-0.6b (офлайн
точнее Parakeet v3 и Ultra?), Voxtral Mini 4B Realtime (GPU-субтитры, ru 6,02 % при 480 мс), Nemotron-3-Diarization
(через NeMo-Speech.cpp или GGUF, как в Vibe).

---

## 4. Что перенять у конкурентов

1. **Выключить spinning ORT** во всех CPU-сессиях (ASR и VAD): `session.intra_op.allow_spinning=0`,
   `session.inter_op.allow_spinning=0` (onnx-asr принимает `sess_options`; у нас `_cpu_options()` в
   `app/asr_onnx.py` — одно место). Для sherpa-onnx — файл провайдера (RealtimeSTT).
2. **Не распознавать заново растущее окно.** Либо потоковая модель (Nemotron 3.5: каждый кадр один раз), либо
   VAD-фразы: черновик — только по текущей фразе, финал — один раз после паузы (Meetily: Silero, min_speech 250 мс,
   redemption 500 мс в живом режиме и 2000 мс в пакетном; принудительный разрез длинной сплошной речи, иначе сегмент
   не закрывается). RealtimeSTT «tail mode»: досчитывать только новый хвост и склеивать с уже распознанным.
3. **Бюджет потоков на всю программу, а не на модель.** OpenWhispr: `min(4, 0.75×CPU)`; Handy: VAD — 1 поток.
   Когда идут одновременно субтитры и очередь расшифровки, сумма потоков не должна превышать физических ядер минус
   1–2 (сейчас каждая сессия берёт `cores//2`, а `os.cpu_count()` считает логические ядра).
4. **Отдельный процесс и пониженный приоритет.** Handy и noScribe держат модели в процессах-воркерах; у нас
   `live_worker.py` уже отдельный — добавить `creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS` (или
   `psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)`) воркерам субтитров и очереди; для очереди можно
   `IDLE_PRIORITY_CLASS`. Дополнительно — режим EcoQoS Windows 11 (`SetProcessInformation` /
   `ProcessPowerThrottling`) для фоновой расшифровки (не проверено в этой сессии).
5. **int8 на CPU у всех десктопных конкурентов**; fp32 Parakeet никто не использует. Экономия памяти ~1,8 ГБ при той же
   скорости (onnx-asr на 9800X3D) — проверить точность int8 на ru.
6. **Пара «быстрый черновик + точный финал»** (RealtimeSTT: Nemotron + Parakeet/Orukeet) — пользователь видит текст сразу,
   а в запись попадает точная версия.
7. **Каналы как подсказка для диаризации** (Meetscribe): микрофон = «я», системный звук — собеседники.
8. **Арена памяти ORT**: в длинных сессиях проверить рост RSS; при росте — `enable_cpu_mem_arena = False`.
9. **Модели с хешами и закреплёнными ревизиями** (Meetily закрепляет ревизию HF и точный размер файлов; RealtimeSTT —
   SHA-256 архивов sherpa-onnx). У нас ревизии уже закреплены — сохранить и для новых моделей.

---

## 5. Что не удалось проверить из песочницы

- Недоступны: onnxruntime.ai (документация по потокам — по выдаче поиска), www.nvidia.com (текст NVIDIA Open Model
  License), dev.to (отчёт о памяти Parakeet), данные HF Open ASR Leaderboard (закрытые датасеты, 401), GitHub API
  (поиск по issues; MCP открыт только для репозиториев пользователя). spdx.org, k2-fsa.github.io, alphacephei.com,
  jsdelivr не запрашивались — использованы GitHub raw и HF.
- Скорость Nemotron 3.5 int8 именно в sherpa-onnx на Windows, точность сторонних ONNX Parakeet Ultra и поведение
  `provider="cpu:<conf>"` в sherpa-onnx 2.0.3 — опубликованных данных нет, нужен замер на ПК.
- Лицензии 3D-Speaker CAM++ и «-nc» варианта Granite 5.0 не открывались напрямую.
