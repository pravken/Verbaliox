# Задание для локальной сессии: замер моделей перевода для живых субтитров (en↔ru)

Цель — выбрать модели для режимов «Качество» и «Скорость» живого перевода. Эталонная видеокарта — **RTX 3080
с 10 ГБ**: модель перевода должна помещаться в видеопамять вместе с моделью распознавания речи (GigaAM или
Whisper turbo). На карте больше 10 ГБ меньшая карта изображается `tools/vram_ballast.py` (шаг 4).

Скрипт: `tools/bench_translate.py` (описание — в его начале). Он не читает и не пишет папку данных программы
(на время работы подставляет пустую временную), модели Ollama только запрашивает. Тестовый набор и
сконвертированный Opus-MT кладёт в `%TEMP%\verbaliox-bench-translate`.

## 1. Что скачать

Ollama — та, что ставит программа (или `ollama serve`), адрес `http://127.0.0.1:11434`.

```
ollama pull gemma4:e2b                               :: «Скорость» сейчас; ~4,6 ГБ на диске (с частями для изображений и звука)
ollama pull gemma4:e4b                               :: «Качество» сейчас при видеокарте от 7,5 ГБ; ~6,6 ГБ
ollama pull translategemma:4b                        :: ~3,3 ГБ; лицензия — см. раздел 5
ollama pull translategemma:12b                       :: по желанию, ~8,1 ГБ: проверить, влезает ли в 10 ГБ вместе с речью
ollama pull hf.co/tencent/Hy-MT3-1.8B-GGUF:Q4_K_M    :: по желанию, 1,35 ГБ, Apache-2.0
ollama pull hf.co/tencent/Hy-MT3-7B-GGUF:Q4_K_M      :: по желанию, 5,15 ГБ, Apache-2.0
```

Hy-MT3 вышел 17.11.2026 (архитектура `hunyuan_v1_dense`). Если Ollama его не загрузит — записать текст ошибки
и версию Ollama, модель пропустить.

**Opus-MT** (`Helsinki-NLP/opus-mt-en-ru` и `opus-mt-ru-en`) скачивать руками не нужно: при первом запуске
скрипт сам конвертирует их в CTranslate2 int8 (нужны torch, transformers и sentencepiece — они уже есть в
`.venv` программы; нужен доступ к huggingface.co). На видеокарте — `int8_float16`, без неё — `int8`.

## 2. Проверка, что всё работает (минута)

Программу на время замера лучше закрыть, кроме Ollama (живые субтитры и очередь не должны занимать карту).

```
.venv\Scripts\python tools\bench_translate.py --out %TEMP%\bt-check --n 5 --models gemma4:e2b opus-mt
```

## 3. Основной замер (≈20–40 минут на видеокарте, без учёта скачивания)

```
.venv\Scripts\python tools\bench_translate.py --out %TEMP%\bt-full --n 100 ^
    --models gemma4:e2b gemma4:e4b translategemma:4b translategemma:12b opus-mt ^
             hf.co/tencent/Hy-MT3-1.8B-GGUF:Q4_K_M hf.co/tencent/Hy-MT3-7B-GGUF:Q4_K_M
```

- 100 строк WMT24++ (`google/wmt24pp`, Apache-2.0) по 5–30 слов, в обе стороны; ru→en — те же пары наоборот.
- Модель общего назначения переводит кодом субтитров (`LiveTranslator._translate_clean`: тот же промпт,
  параметры, очистка и повтор). TranslateGemma и Hy-MT — промптом со своей карточки модели; для сравнения
  можно добавить запуск с промптом субтитров: `translategemma:4b@app`.
- Если большая модель идёт медленно: `translategemma:12b#40` — только первые 40 строк; таблица тогда
  добавит столбец chrF++ всех моделей на тех же 40 строках.
- Прерванный запуск не теряет готовые модели: `results.json` пишется после каждой.

## 4. Помещается ли в 10 ГБ вместе с речью

На карте больше 10 ГБ в отдельном окне:

```
.venv\Scripts\python tools\vram_ballast.py --card 10 --asr
```

(держит память так, чтобы свободно было как на 10-гигабайтной карте, и загружает GigaAM как во время
записи). Модель речи он берёт из `VERBALIOX_MODELS_DIR`: по правилам проекта — копия папки моделей во
временной папке (`set VERBALIOX_MODELS_DIR=%TEMP%\models-copy` перед запуском), не настоящая `models`.
Затем повторить шаг 3 с `--out %TEMP%\bt-10gb` для моделей, которые претендуют на «Качество»
(`gemma4:e4b`, `translategemma:12b`, `hf.co/tencent/Hy-MT3-7B-GGUF:Q4_K_M`). Признак «не влезла»: столбец
«Loaded, MB (of it VRAM)» показывает VRAM заметно меньше Loaded (часть слоёв ушла на процессор), и время на
строку растёт в разы. Для субтитров нужна медиана ≲0,5 с и p90 ≲1 с (черновик фразы переводится раз в 1,2 с).

## 5. COMET (по желанию, ≈5–15 минут)

`unbabel-comet` нет в `.venv` программы, ставить его туда не нужно — отдельное окружение:

```
python -m venv %TEMP%\comet-venv
%TEMP%\comet-venv\Scripts\pip install unbabel-comet
%TEMP%\comet-venv\Scripts\python tools\bench_translate.py --rescore %TEMP%\bt-full\results.json --comet
```

Модель `Unbabel/wmt22-comet-da` (Apache-2.0, ~2,3 ГБ) скачается в кэш Hugging Face. Без CUDA-сборки torch
считает на процессоре — дольше, но результат тот же.

## 6. Что прислать / записать

- `results.md` и `results.json` из `%TEMP%\bt-full` (и `bt-10gb`, если был шаг 4). В них только публичный
  тестовый набор и переводы — личных данных нет.
- Версию Ollama, модель видеокарты и процессора (скрипт пишет их в начало `results.md`).
- По результатам — `bench-report/translation-2026-11.md`: таблица в обе стороны, лицензии, условия,
  оговорки (ru→en — обратный перевод; время зависит от нагрузки ПК) и рекомендация для «Качество» и
  «Скорость» (с учётом 10 ГБ вместе с речью). Затем, если выбор меняется, — `FAST_MODEL_HINTS` и
  рекомендация модели в `app/hardware.py` отдельным коммитом.

## 7. Лицензии — перепроверить по карточкам перед выбором

| Модель | Лицензия на карточке | Вердикт |
|---|---|---|
| gemma4:e2b / e4b | Apache-2.0 (`google/gemma-4-E2B-it`) | можно |
| translategemma:4b / 12b | Gemma Terms of Use (`google/translategemma-4b-it`, `-12b-it`: license `gemma`) | **не Apache: свои условия и запреты на виды использования. Как и Gemma 2 раньше, без решения автора в программу не брать — спросить** |
| Hy-MT3-1.8B / 7B (и GGUF) | Apache-2.0, «does not impose any additional restrictions» | можно; проверить, что карточка и `LICENSE.txt` GGUF-репозитория не изменились |
| Hy-MT2-1.8B / 7B | Apache-2.0 | можно (в замер не входит, Hy-MT3 новее) |
| HY-MT1.5-1.8B / 7B, Hunyuan-MT-7B | Tencent HY Community License: не действует в ЕС, Великобритании и Южной Корее | **нельзя** — не мерить |
| Opus-MT en-ru / ru-en | Apache-2.0 / CC-BY-4.0 (атрибуция) | можно; если войдёт в программу — добавить в таблицу лицензий README |
| WMT24++ (данные) | Apache-2.0 | можно; в репозиторий не кладётся, скрипт скачивает |
| Unbabel/wmt22-comet-da | Apache-2.0 | только для оценки, в программу не входит |
