# Changelog · Журнал изменений

Each release page takes its text from here, the section with its number: English first, then Russian.
Betas (`vX.Y.Z-beta.N`) show the sections of their coming version.

Описание каждой версии берётся отсюда в страницу релиза (раздел с её номером): сначала английский, затем
русский. Бета-версии (`vX.Y.Z-beta.N`) показывают раздел своей будущей версии.

## 0.7.2 — English

- **A calendar of the week or the month:** «Calendar» on the home page shows the calendar's meetings and
  the recordings side by side; a recorded meeting opens its recording, a recording outside meetings is
  shown on its own.
- **«Unload all» really unloads:** every model goes out of memory, Ollama's too (also one loaded before the
  app started), and the app waits until Ollama has let it go, stopping its runner if it keeps the model.
  The button is in the Models window and in Settings.
- **Import:** the window closes at once and files go to the library in the background, with their progress
  in a notice; the link and the path on the disk are fields in sight, not behind buttons.
- **Less on the system disk:** the setup keeps uv's downloads and the Python it installs in the program
  folder (the download cache is removed after the install), and when the app installs Ollama its models
  go to the program folder too.
- **The installer always shows the folder:** it says where Verbaliox is installed; another folder moves the
  program there with its environment and models, and asks whether to remove the old folder.
- Studio: the column titles of the captions no longer let the lines show above and through them.

## 0.7.1 — English

- **First start on a PC where uv is found but does not run** («The system cannot execute the specified
  program»: a dead shortcut left by winget, or a company policy blocking programs in AppData): the setup
  takes uv only if it runs and looks further, and when uv cannot make a working environment it makes it
  on Python 3.11 of python.org with pip. The environment's Python is checked to run before the libraries
  are installed. The dubbing setup and the in-app updater skip a uv that does not run too.

## 0.7.0 — English

The name is now **Verbaliox**. Highlights of this version (the betas below list everything):
- **An installer** (`Verbaliox-Installer-vX.Y.Z.exe`) next to the portable zip, and a setup window instead of
  the console at the first start, with progress and a log.
- **A simpler first start:** ready sets of models for Russian, Russian and English, or many languages; AI
  analysis on this computer, in the cloud or none.
- **A model per language:** Russian speech to GigaAM, other languages to the main model, with the language
  heard from the first minute; model meters show accuracy, speed and load.
- **Dubbing in the VoxCPM2 voice** instead of Chatterbox.
- FFmpeg downloads by itself; two code reviews of the whole program fixed security, installer and
  transcription issues.

### Since the eighth beta
- **First start on a PC where uv does not install through winget:** the setup finds uv where winget leaves
  it, falls back to the uv installer of astral.sh, and without uv takes only Python 3.11 (installing it
  from python.org when missing). An old Python 2.7 on the PC no longer breaks the setup with «No module
  named venv»; a failed step says what is missing instead of a chain of «path not found». The dubbing
  environment finds uv the same way.
- The installer is called `Verbaliox-Installer-vX.Y.Z.exe` (was `Verbaliox-Setup-…`).

### In the eighth beta (0.7.0-beta.8)
- **First start with a cloud model** no longer loses the choices of the welcome window (models, Russian
  routing, language); the cloud consent is asked in Settings → Analysis right after.
- **The speech language chosen for a recording stays chosen:** «several languages» or «auto» are no longer
  replaced by the language heard, so «Transcribe again» and Retry use your choice. GigaAM / Parakeet tell
  German, French, Spanish, Italian, Portuguese, Dutch, Polish and Ukrainian transcripts apart from English.
- A fragment of a cancelled or failed transcription no longer appears as a transcript version «auto».
- Deleting GigaAM or Parakeet no longer stops live captions running on the other one; it waits for live
  captions and transcription like Whisper.
- Live captions skip one window they could not recognize instead of restarting the recognizer.
- A screen recording recovered after a crash keeps its picture.
- A summary no longer unloads the speech models of a transcription running at the same time; a download by
  link is not started twice.
- The setup window opens at once (the video card is checked in the background) and its cancel also stops
  the installers winget runs. Unused interface texts removed; more tests.

### In the seventh beta (0.7.0-beta.7)
- **First start:** a set with several models besides GigaAM (say Parakeet and Whisper Turbo) asks which
  one is the main model for other languages and mixed speech, instead of taking the first.
- Moving the data folder to the new name rewrites only stored file paths: a transcript or note that
  mentions the old folder stays as written.

### In the sixth beta (0.7.0-beta.6)
- **An installer:** `Verbaliox-Installer-vX.Y.Z.exe` installs the program for your user (no administrator
  rights) into `%LOCALAPPDATA%\Programs\Verbaliox`, with a Start menu entry, an optional desktop icon and
  an uninstaller in «Installed apps» that asks before removing the recordings and models. The zip stays
  as the portable version.
- **A new version over an older one:** when the installer or an unpacked zip brings other libraries, the
  setup window updates the program environment at the next start. The recordings, settings and models stay.
- «Installed apps» shows the version the program updated itself to; uninstalling also removes «Start with
  Windows».
- A Whisper model downloaded as the model for Russian no longer replaces the main model.
- Language detection: a first minute of silence or music no longer decides, Serbian, Kazakh and other
  Cyrillic languages stay with the main model, and the check no longer loads a second copy of the model.
- Security: a backup restored from elsewhere can no longer put markup into the page through speaker
  colours or segment numbers; the speech model settings take only models of the catalog.
- Model meters show memory on the processor on a PC without a video card; the FFmpeg download error is
  translated; batch files use Windows line endings.

### In the fifth beta (0.7.0-beta.5)
- **A simpler first start.** The welcome window offers ready sets: meetings in Russian, Russian and
  English, many languages, or your own choice — each model says what it is for and how much it weighs.
  AI analysis is a separate step: none (transcripts only), on this computer or a cloud model.
- **A model per language.** Russian speech can go to its own model (GigaAM) and other languages to the
  main one (Whisper Turbo or Parakeet); with the language left to detection, the first minute decides.
  Settings → Speech models → «Model for Russian speech».
- **FFmpeg downloads by itself** at the first start: recording, import and export work without a visit
  to the settings.
- **A setup window instead of the console** at the very first start: what the program needs and what each
  part is for (the environment, the NVIDIA driver — CUDA comes with the environment, FFmpeg, Ollama if you
  want local analysis), confirmed with «Install», with progress and a log. Ollama installs silently and its
  own window no longer pops up.
- **Model meters:** every speech and analysis model shows accuracy (per language), speed on this
  computer and load in five dots, with the measured numbers in the tooltip.

### In the fourth beta (0.7.0-beta.4)
- API keys are stored under the program's new name: keys saved before are read and saved again at the
  first start. Install this beta in place of the third one.

### In the third beta (0.7.0-beta.3)
- **A new name: Verbaliox** — the window, the launcher `Verbaliox.exe`, the repository and the release
  files. At the first start the library, settings and API keys move to the data folder
  `%LOCALAPPDATA%\Verbaliox` by themselves; Obsidian notes and backups made before are still recognised.

### In the second beta (0.7.0-beta.2)
- **Dubbing:** an environment made for Chatterbox before (updated with git or by an older version) is
  no longer taken as ready, which failed the dub with «No module named 'voxcpm'». The Dub window offers to
  install the environment again.
- Release pages and this changelog put English first; the README has a cover; the license names
  pravken as the copyright holder.

### In the first beta (0.7.0-beta.1)
Everything of the 0.6.0 betas (Python 3.11, the audit fixes, the new look), and:
- **Dubbing in the VoxCPM2 voice instead of Chatterbox.** In a blind listening test the new model won every pair:
  correct Russian stress, 8 times fewer broken phrases, numbers and dates read as words in the target language.
  About 1.7 times slower, and it needs about 7 GB of VRAM. The dubbing environment is installed again once, the
  weights (about 5 GB) are downloaded on the first dub; the old Chatterbox weights can be deleted in Settings →
  Speech synthesis. The one GPL package (pykakasi) has left the environment.
- The synthesis settings have one «Reference adherence» (1–3) instead of Chatterbox's expressiveness and CFG.
- Dubbing environment: transformers 5.22 closes four vulnerability advisories.

## 0.7.2

- **Календарь на неделю или месяц:** кнопка «Календарь» на главной показывает встречи календаря и записи
  вместе; записанная встреча открывает свою запись, запись вне встреч видна отдельно.
- **«Выгрузить всё» действительно выгружает:** из памяти уходят все модели, в том числе модели Ollama
  (и загруженные до запуска программы), а программа ждёт, пока Ollama их отпустит, и останавливает её
  процесс, если модель не уходит. Кнопка есть в окне «Модели» и в настройках.
- **Импорт:** окно закрывается сразу, а файлы добавляются в медиатеку в фоне, с прогрессом в уведомлении;
  поля для ссылки и пути на диске видны сразу, а не спрятаны за кнопками.
- **Меньше на системном диске:** установка держит загрузки uv и его Python в папке программы (кэш
  загрузок удаляется после установки), а модели Ollama, если её ставит программа, тоже лежат в папке
  программы.
- **Установщик всегда показывает папку:** пишет, где Verbaliox уже установлен; при выборе другой папки
  программа переезжает туда вместе со средой и моделями, а установщик спрашивает, удалить ли старую папку.
- Студия: заголовки колонок субтитров больше не пропускают строки над собой и сквозь себя.

## 0.7.1

- **Первый запуск на ПК, где uv находится, но не запускается** («The system cannot execute the specified
  program»: битый ярлык, оставленный winget, или политика компании, запрещающая программы из AppData):
  установка берёт uv, только если он запускается, и ищет дальше, а если uv не может сделать рабочую
  среду, делает её на Python 3.11 с python.org через pip. Перед установкой библиотек проверяется, что
  Python среды запускается. Установка дубляжа и встроенное обновление тоже пропускают незапускающийся uv.

## 0.7.0

Новое имя — **Verbaliox**. Главное в этой версии (всё по бетам — ниже):
- **Установщик** (`Verbaliox-Installer-vX.Y.Z.exe`) рядом с портативным zip и окно установки вместо консоли
  при первом запуске, с прогрессом и журналом.
- **Простая первая настройка:** готовые наборы моделей для русского, русского с английским или многих
  языков; ИИ-анализ на компьютере, в облаке или без него.
- **Модель под язык:** русскую речь распознаёт GigaAM, другие языки — основная модель, язык определяется
  по первой минуте; шкалы моделей показывают точность, скорость и нагрузку.
- **Дубляж голосом VoxCPM2** вместо Chatterbox.
- FFmpeg скачивается сам; два ревью всего кода исправили ошибки безопасности, установщика и распознавания.

### После восьмой беты
- **Первый запуск на ПК, где uv не ставится через winget:** установка находит uv там, куда его кладёт winget,
  при неудаче ставит uv установщиком с astral.sh, а без uv берёт только Python 3.11 (и ставит его с
  python.org, если его нет). Старый Python 2.7 на компьютере больше не ломает установку ошибкой «No module
  named venv»; неудачный шаг говорит, чего не хватает, вместо цепочки «путь не найден». Окружение дубляжа
  находит uv так же.
- Установщик называется `Verbaliox-Installer-vX.Y.Z.exe` (был `Verbaliox-Setup-…`).

### В восьмой бете (0.7.0-beta.8)
- **Первый запуск с облачной моделью** больше не теряет выбор окна приветствия (модели, модель для русского,
  язык); согласие на облако спрашивается сразу после этого в «Настройки → Анализ».
- **Язык речи, выбранный для записи, остаётся выбранным:** «несколько языков» и «авто» больше не заменяются
  услышанным языком, поэтому «Распознать заново» и «Повторить» берут ваш выбор. GigaAM и Parakeet отличают
  от английского немецкие, французские, испанские, итальянские, португальские, нидерландские, польские и
  украинские расшифровки.
- Обрывок отменённого или сбойного распознавания больше не появляется как версия расшифровки «авто».
- Удаление GigaAM или Parakeet больше не останавливает живые субтитры на другой модели и, как у Whisper,
  ждёт окончания субтитров и распознавания.
- Живые субтитры пропускают одно нераспознанное окно, а не перезапускают распознавание.
- Запись экрана, восстановленная после сбоя, остаётся видео.
- Обзор больше не выгружает модели распознавания, пока идёт расшифровка; скачивание по ссылке не
  запускается дважды.
- Окно установки открывается сразу (видеокарта проверяется в фоне), а «Отмена» в нём останавливает и
  установщики, запущенные через winget. Убраны неиспользуемые тексты интерфейса, добавлены тесты.

### В седьмой бете (0.7.0-beta.7)
- **Первый запуск:** если в наборе кроме GigaAM несколько моделей (например, Parakeet и Whisper Turbo),
  мастер спрашивает, какая из них основная для других языков и смешанной речи, а не берёт первую.
- При переносе папки данных на новое имя меняются только сохранённые пути к файлам: расшифровка или
  заметка, где упомянута старая папка, остаётся как была.

### В шестой бете (0.7.0-beta.6)
- **Установщик:** `Verbaliox-Installer-vX.Y.Z.exe` ставит программу для вашего пользователя (без прав
  администратора) в `%LOCALAPPDATA%\Programs\Verbaliox`, с ярлыком в «Пуске», значком на рабочем столе по
  желанию и удалением через «Установленные приложения», которое спрашивает, стирать ли записи и модели.
  Zip остаётся портативной версией.
- **Новая версия поверх старой:** если установщик или распакованный zip приносит другие библиотеки, окно
  установки при следующем запуске обновит среду программы. Записи, настройки и модели остаются.
- «Установленные приложения» показывают версию, до которой программа обновилась сама; при удалении
  убирается и «Запуск вместе с Windows».
- Модель Whisper, скачанная как модель для русского, больше не заменяет основную.
- Определение языка: первая минута тишины или музыки больше не решает, сербский, казахский и другие
  кириллические языки остаются у основной модели, а проверка не загружает вторую копию модели.
- Безопасность: резервная копия из чужих рук больше не может внести разметку в страницу через цвета
  участников или номера фраз; в настройки моделей распознавания попадают только модели из каталога.
- Шкалы моделей на ПК без видеокарты показывают оперативную память; ошибка загрузки FFmpeg переводится;
  bat-файлы — с переводами строк Windows.

### В пятой бете (0.7.0-beta.5)
- **Простая первая настройка.** Окно приветствия предлагает готовые наборы: встречи на русском, русский
  и английский, много языков или своя настройка — у каждой модели написано, для чего она и сколько весит.
  ИИ-анализ — отдельный шаг: без него (только расшифровка), на этом компьютере или облачная модель.
- **Модель под язык.** Русскую речь распознаёт своя модель (GigaAM), остальные языки — основная (Whisper
  Turbo или Parakeet); если язык не указан, его определяет первая минута записи. «Настройки → Модели речи →
  Модель для русской речи».
- **FFmpeg скачивается сам** при первом запуске: запись, импорт и экспорт работают без похода в настройки.
- **Окно установки вместо консоли** при самом первом запуске: что нужно программе и для чего каждая часть
  (среда программы, драйвер NVIDIA — CUDA входит в среду, FFmpeg, Ollama — если нужен анализ на компьютере),
  подтверждение кнопкой «Установить», прогресс и журнал. Ollama ставится тихо, её собственное окно больше не
  выскакивает.
- **Шкалы моделей:** у каждой модели распознавания и анализа — точность (по языкам), скорость на этом
  компьютере и нагрузка в пяти делениях, с цифрами замеров в подсказке.

### В четвёртой бете (0.7.0-beta.4)
- API-ключи хранятся под новым именем программы: сохранённые раньше читаются и пересохраняются при первом
  запуске. Эту бету можно ставить вместо третьей.

### В третьей бете (0.7.0-beta.3)
- **Новое имя — Verbaliox**: окно, лаунчер `Verbaliox.exe`, репозиторий и файлы релиза. При первом запуске
  медиатека, настройки и API-ключи сами переходят в папку данных `%LOCALAPPDATA%\Verbaliox`; заметки Obsidian
  и резервные копии, сделанные раньше, по-прежнему узнаются.

### Во второй бете (0.7.0-beta.2)
- **Дубляж:** окружение, сделанное раньше для Chatterbox (обновлённое через git или старой версией), больше
  не считается готовым — из-за этого дубляж падал с «No module named 'voxcpm'». Окно «Дубляж» предлагает
  установить окружение заново.
- На страницах релизов и в этом журнале английский раздел идёт первым; в README появилась обложка; в лицензии
  правообладатель — pravken.

### В первой бете (0.7.0-beta.1)
Всё из бет 0.6.0 (Python 3.11, исправления по аудиту, новый вид программы) и:
- **Дубляж голосом VoxCPM2 вместо Chatterbox.** В слепом сравнении на слух новая модель выиграла все пары:
  правильные ударения в русском, в 8 раз меньше срывов, числа и даты читаются словами на языке перевода.
  Медленнее примерно в 1,7 раза и требует около 7 ГБ видеопамяти. Окружение дубляжа ставится заново один раз,
  веса (около 5 ГБ) скачиваются при первом дубляже; старые веса Chatterbox можно удалить в «Настройки → Синтез
  речи». Из окружения ушёл единственный пакет с лицензией GPL (pykakasi).
- В настройках синтеза вместо «Выразительности» и CFG Chatterbox — одна настройка «Следование образцу» (1–3).
- Окружение дубляжа: transformers 5.22 закрывает четыре уведомления об уязвимостях.

## 0.6.0 — English

### In the fourth beta (0.6.0-beta.4)
- **Python 3.11.** The app and the dubbing environment move to Python 3.11, which closes the filelock
  and Pillow vulnerabilities that cannot be fixed on 3.10. The environment is made again once, by
  itself, at the first start after the update: about 7 GB of libraries are downloaded (about 6 GB more
  for dubbing when it is installed again), usually 5–15 minutes. Until the new environment is ready the
  old one works; if the install fails, the old one stays and the next try is a day later.
- Demucs weights (background separation in dubbing) come from a pinned version, like the other models.

### In the third beta (0.6.0-beta.3)
Fixes after an independent audit.
- **Restoring a backup** from someone else does nothing on this computer any more: the copy's own
  database commands, its queue of files to delete and paths leading to your files are removed; sound
  goes back only into the recording folders. Your sound retention setting stays.
- **Private recordings** (local analysis only) stay out of a cloud model in «Since last time», and a
  question about the whole library no longer sends all other transcripts in full.
- **Export without fillers** no longer moves translations onto neighbouring lines or loses a dictation's
  translation.
- **Installing Ollama** from the app works again.
- **Dictation hotkeys:** «Turn off» is saved; the dictation hotkey shows whether it works. A press while
  the last dictation is recognized no longer upsets it.
- **An export waiting for a transcript or translation** keeps its options, goes into the date folder and
  is listed with the recording. Changing the language in the Dub window keeps it.
- **Dubbing** no longer stops at 88 % when the model of the settings is not in Ollama.
- **Video subtitles:** the source picked as the output by mistake is not listed under Copies.
- **Import** takes sound and video only; .opus, .m4v, .mka and more are added.
- Translated SRT and VTT follow the «Names» option.
- «Open the last recording» from the tray right after start, a failed cancel of a pending export is
  reported, `update.bat` leaves no file in the temp folder.

### In the second beta (0.6.0-beta.2)
- **Menus and popovers** are one real glass; they grow from where they were opened and leave the same
  way. With Windows transparency effects off the fill is solid.
- **Undo instead of questions:** a task, a folder, a translation, an analysis section, a record preset,
  an own template and the dictionary go at once and can be brought back for 7 s. Questions stay for
  what cannot be undone, and their button names the action.
- **Four kinds of notices:** status, done, warning, error. An error stays until closed; none leaves
  while the pointer is on it.
- **Names:** Home is «Today», the system folders are «From the Studio» and «Imported», «Transcribe
  again» everywhere, the «Speech models» tab.
- **Settings:** Interface is part of General, model comparison and dubbing are under «Advanced»;
  Recognition starts with «Choose automatically», precision in words under «More»; scale up to 150 %,
  on the first start following the Windows text size.
- **Above the text** the recognition row folds into the model mark «GigaAM v3 ▾»; the **import window**
  shows the model and language, the rest under «Change».
- **Models:** a tile under the hardware opens every model beside the library — running, installed and
  downloadable; the CPU and GPU marks light while a model works there. The analysis model choice says
  what suits this computer and how much video memory it needs. Qwen 7B Standard, Qwen 14B Pro and
  Mistral 7B are no longer offered.
- **Recording:** the microphone and the computer sound each show their own level.
- **Player and text:** drag the time bubble over the wave; the current chapter stays in the middle;
  video buttons on the black panel beside the picture; a double click on a line no longer opens the
  editor. The recording's name is shown once, in full, above the text.
- **Library:** filters by type, source, state, readiness and language; the ⇅ menu stays open; dragging
  opens folders and moves the recording at once.
- **Type and accessibility:** seven text sizes instead of 25; captions and blue buttons up to the
  contrast norm; Windows «show less motion» and «more contrast»; soft edges of scrolled lists; nothing
  under 11 px.
- **update.bat** updates a git-cloned folder next to Verbaliox.exe.
- Fixed: a dialog no longer closes when a text selection is released over its backdrop; a menu at the
  bottom of the window opens upward; following the playback waits while you scroll; Record in the open
  Studio uses the source it shows; clocks and badges are monospace again, letters like ą, č, ł from Inter.

### A new look
- **A top bar instead of tabs:** Today, Tasks, the open recording (Transcript, ✦ Analysis, Speakers,
  ⋯ menu), Studio, ✦ Assistant; a status bar below (processor, video card, memory, queue). Interface
  scale in Settings → General (75–150 %).
- **The red Record button** records at once in any view with the last studio settings; a second press
  stops and queues the recording.
- **Today:** recent recordings with their summaries, today's calendar meetings over a working day you
  set (also past midnight), auto-recording of all meetings with exceptions and a question before
  in-person ones, the queue, My tasks, dictation.
- **Import window:** files, links and paths in one list; model, language, speakers, sound processing
  before recognition, speaker separation, analysis; an estimated time; remember the choice or stop asking.
- **Player:** a waveform from the real loudness with speaker colours and chapters; repeat a line or an
  A–B span, marks, speed from 0.25×; ✦ Sound — studio voice, skipping pauses without speech, the dub
  track; a double click on the wave shows the place in the text; save the sound as MP3 / WAV, also
  without fillers and pauses.
- **"Without fillers"** only hides "um", "like" and repeats in the view; the recording's text stays.
  Older recordings cleaned before get "Restore the original text". In exports it is an option next to
  timecodes and names.
- **Recording details** (Ctrl+I): file, dates, format, recognition, sound processing, saved copies.
- **Analysis:** sections on the left, a configurable overview, your templates, a letter to the
  participants, a question about the recording.
- **Speakers:** cards with role and "This is me", voice and calendar suggestions, merge and split,
  talk statistics; an "All people" directory of people and departments across recordings.
- **Tasks** from all recordings: by person, due date or recording; assignees can be participants,
  people outside the meeting, departments or companies; the quote they came from; a due date;
  a calendar with drag and drop; a summary for a period; "+ Task".
- **Studio:** ready-made sets of settings, levels and a microphone check, the calendar meeting, marks,
  your notes while recording, full-window text.
- **Assistant:** conversations with history, where to look (library, folder, period, chosen
  recordings), answers whose sources lead to the place in a recording, saving an answer.
- **Settings** are a page: search across all settings, reset a section, changes saved at once.

### New
- **Dictations in the library**, in a system folder "Dictations" (sound, text, translation; local analysis only).
- **Start with Windows** in the tray without a window; closing the window keeps the app in the tray;
  a downloaded update installs while the window is hidden and nothing runs.
- **Recognition options per recording:** noise reduction, loudness levelling, quiet parts, skip silence,
  speaker separation, language, number of speakers; remembered for the recording.
- **Library:** fold / unfold everything; a dot on a folded folder or day holding the open recording.

### Changed
- "Promises" are called "Tasks" everywhere.
- Library badges: only what needs attention always; analysis, translations, dubs on hover and on the
  selected row ("View → Badges → All, always" for the old list).
- The "Checked" mark above the text is gone; the model comparison takes the recording's text as the reference.
- Recording and processing errors name the cause and lead to the setting; technical text under "Details".

### Security
- **torch 2.11** (CUDA 12.6) instead of 2.6 (PYSEC-2026-2286); the update downloads about 2.5 GB once.
- Hugging Face models from fixed commits; the dubbing environment from a lock with hashes.

### Fixed
- Dictation with translation (and analysis, translation, dubbing) no longer picks the embedding model
  (bge-m3) as the text model, which Ollama refused with "400 Bad Request".
- The player waveform is back for processed recordings.
- The library view / sort menu opens again, a folder lights up when a recording is dragged over it.
- Copying an analysis, reprocessing, deleting a recording and a few other actions no longer end
  silently after they are done.

---

## 0.6.0

### В четвёртой бете (0.6.0-beta.4)
- **Python 3.11.** Программа и окружение дубляжа переходят на Python 3.11: это закрывает уязвимости
  filelock и Pillow, которые на 3.10 не исправить. Окружение пересоздаётся один раз, само, при первом
  запуске после обновления: скачивается около 7 ГБ библиотек (у дубляжа — ещё около 6 ГБ при его
  переустановке), обычно 5–15 минут. Пока новое окружение не готово, работает прежнее; если установка
  не удалась, прежнее остаётся на месте, а новая попытка будет через день.
- Веса Demucs (отделение фона в дубляже) скачиваются с закреплённой версии, как и остальные модели.

### В третьей бете (0.6.0-beta.3)
Исправления по независимому аудиту.
- **Восстановление резервной копии** чужого архива больше ничего не делает на этом компьютере: из базы
  копии убираются её собственные команды, очередь удаления файлов и пути, ведущие к вашим файлам;
  звук возвращается только в папки записей. Срок хранения звука остаётся вашим.
- **Приватные записи** («только локальный анализ») не попадают в облачную модель через «С прошлого раза»,
  а вопрос ко всей медиатеке не отправляет в облако все остальные расшифровки целиком.
- **Экспорт «Без запинок»** больше не сдвигает переводы на соседние реплики и не теряет перевод диктовки.
- **Установка Ollama** из программы снова работает.
- **Горячие клавиши диктовки:** «Отключить» сохраняет настройку; у диктовки видно, работает ли клавиша.
  Нажатие во время распознавания прошлой диктовки ничего не сбивает.
- **Экспорт, который ждал расшифровку или перевод,** сохраняется с выбранными опциями, в папку по дате и
  появляется в копиях записи. Смена языка в окне дубляжа не теряет такой экспорт.
- **Дубляж** не останавливается на 88 %, если модели из настроек нет в Ollama.
- **Субтитры к видео:** исходный файл, выбранный по ошибке как место сохранения, не попадает в «Копии».
- **Импорт:** принимаются только звук и видео; добавлены .opus, .m4v, .mka и другие.
- В переведённых SRT и VTT работает галочка «Имена».
- «Открыть последнюю запись» из трея сразу после запуска, отмена отложенного экспорта с сообщением об
  ошибке, `update.bat` не оставляет файл во временной папке.

### Во второй бете (0.6.0-beta.2)
- **Меню и всплывающие панели** — одно настоящее стекло; растут из места, где их открыли, и так же
  плавно закрываются. При выключенных эффектах прозрачности Windows — сплошной фон.
- **«Отменить» вместо вопросов:** задача, папка, перевод, раздел анализа, набор записи, свой шаблон
  и словарь удаляются сразу, 7 секунд можно вернуть. Вопрос остался только для необратимого, и его
  кнопка называет действие («Удалить папку», а не «OK»).
- **Уведомления четырёх видов:** состояние, готово, предупреждение, ошибка. Ошибка держится до закрытия,
  ни одно уведомление не исчезает под курсором.
- **Названия:** «Главная» → «Сегодня», системные папки «Из студии» и «Импортированные»,
  «Расшифровать заново» везде одинаково, вкладка «Модели речи».
- **Настройки:** «Интерфейс» вошёл в «Общие», сравнение моделей и дубляж — в группе «Для опытных»;
  в «Распознавании» — «Подбирать автоматически», точность словами в «Дополнительно»; масштаб до 150 %,
  при первом запуске — по размеру текста Windows.
- **Над текстом** строка распознавания свёрнута в метку модели «GigaAM v3 ▾»; **окно импорта** — модель
  и язык, остальное по «Изменить».
- **Модели:** плитка под оборудованием открывает все модели рядом с медиатекой — работающие,
  установленные и те, что можно скачать; отметки CPU и GPU горят, пока на устройстве работает модель.
  Выбор модели анализа подсказывает, что подойдёт этому компьютеру и сколько видеопамяти нужно.
  Из каталога убраны Qwen 7B Standard, Qwen 14B Pro и Mistral 7B.
- **Запись:** у микрофона и звука компьютера свои уровни — в красной кнопке и в студии.
- **Плеер и текст:** пузырёк времени над волной можно тянуть; текущая глава всегда посередине ленты;
  кнопки видео — на чёрной панели рядом с картинкой; двойной щелчок по строке больше не открывает
  редактор. Название записи — один раз, полностью, над текстом.
- **Медиатека:** фильтры по типу, источнику, состоянию, готовности и языку; меню ⇅ не закрывается
  после выбора; перетаскивание раскрывает папку и переносит запись сразу.
- **Шрифты и доступность:** семь размеров текста вместо 25; контраст подписей и синих кнопок до нормы;
  режимы Windows «меньше движения» и «больше контраста»; мягкие края у прокрутки; ничего мельче 11 px.
- **update.bat** — обновление папки, склонированной через git, рядом с Verbaliox.exe.
- Исправлено: окно не закрывается, если выделение текста отпустить на фоне; меню у нижнего края окна
  открывается вверх; автопрокрутка не тянет текст, пока вы его листаете; «Запись» в открытой студии
  пишет с показанным источником; часы и бейджи снова моноширинным шрифтом, буквы ą, č, ł из Inter.

### Новый вид программы
- **Верхняя панель вместо вкладок:** «Сегодня», «Задачи», открытая запись («Расшифровка», «✦ Анализ»,
  «Участники», меню ⋯), «Студия», «✦ Ассистент». Внизу строка состояния: процессор, видеокарта,
  память и очередь. Масштаб интерфейса — в «Настройки → Общие» (75–150 %).
- **Красная кнопка «Запись»** пишет сразу, в любом окне, с последними настройками студии. Второе
  нажатие останавливает запись, она уходит на распознавание.
- **Сегодня:** недавние записи с итогами, встречи календаря на рабочий день (его начало и конец
  задаются, в том числе через полночь), автозапись всех встреч с исключениями и вопросом перед очной
  встречей, очередь обработки, «Мои задачи», диктовка.
- **Окно импорта:** файлы, ссылки и пути одним списком; модель, язык, число участников, обработка
  звука перед распознаванием, разделение по голосам и анализ; примерное время. Выбор можно запомнить
  или больше не спрашивать.
- **Плеер:** волна по настоящей громкости с цветами участников и главами; повтор реплики и отрезка
  A–B, отметки, скорость от 0,25×; «✦ Звук» — студийный голос, пропуск пауз без речи, дорожка
  с озвучкой. Двойной щелчок по волне показывает это место в тексте. Звук сохраняется в MP3 или WAV,
  а также без запинок и пауз.
- **«Без запинок»** только скрывает «ну», «как бы», «э-э» и повторы при показе: текст записи не
  меняется. Для старых записей, где текст уже чистили, есть «Вернуть исходный текст». В экспорте это
  отдельная галочка вместе с таймкодами и именами.
- **Сведения о записи** (Ctrl+I): файл, даты, формат, распознавание, обработка звука и сохранённые
  копии со «Слушать», «Показать в папке» и «Удалить».
- **Анализ:** разделы слева, настраиваемый обзор, свои шаблоны, письмо участникам, вопрос по записи.
- **Участники:** карточки с ролью и «Это я», подсказки по голосу и по приглашённым из календаря,
  объединение и разделение участников, статистика разговора. Справочник «Все люди» — люди и отделы
  из всех записей.
- **Задачи** из всех записей: по людям, срокам или записям; исполнитель может быть участником,
  человеком не со встречи, отделом или компанией; цитата из записи; срок датой; календарь
  с перетаскиванием; сводка за период; «+ Задача».
- **Студия:** готовые наборы настроек, уровни и проверка микрофона, встреча из календаря, отметки,
  свои заметки по ходу записи, текст на всё окно.
- **Ассистент:** разговоры с историей, где искать (вся медиатека, папка, период, выбранные записи),
  ответы с источниками, ведущими к месту в записи, сохранение ответа.
- **Настройки** — отдельная страница: поиск по всем настройкам, сброс раздела, изменения сохраняются
  сразу.

### Новое
- **Диктовки в медиатеке:** каждая диктовка сохраняется записью в системной папке «Диктовки» — звук,
  текст и перевод. Папка только для локального анализа. Отключается в настройках диктовки.
- **Запуск вместе с Windows** в трее, без окна, и закрытие окна, которое оставляет программу в трее
  («Настройки → Общие»). Скачанное обновление ставится само, пока окно скрыто и ничего не идёт.
- **Параметры распознавания у записи:** шумоподавление, выравнивание громкости, подъём тихих мест,
  пропуск тишины, разделение по голосам, язык и число участников. Запоминаются у записи.
- **Медиатека:** «Свернуть всё / Развернуть всё»; точка у свёрнутой папки или дня, где открытая запись.

### Изменено
- «Обещания» теперь везде называются «Задачи».
- Значки в медиатеке: всегда видно только важное; анализ, переводы и дубляж — при наведении и у
  выбранной записи («Вид → Значки → Все всегда» — как раньше).
- Убрана отметка «Проверено» над текстом. В «Сравнении моделей» эталоном служит текст записи.
- Ошибки записи и обработки называют причину и ведут к нужной настройке; технический текст — за «Подробнее».

### Безопасность
- **torch 2.11** (CUDA 12.6) вместо 2.6: закрыта уязвимость `torch.load` (PYSEC-2026-2286). Обновление
  один раз скачает около 2,5 ГБ. Скорость распознавания та же или выше, точность та же.
- Модели Hugging Face скачиваются с закреплённых коммитов, а не с `main`; окружение дубляжа ставится
  из lock-файла с хешами.

### Исправлено
- Диктовка с переводом (и анализ, перевод, дубляж) больше не берёт модель поиска по смыслу (bge-m3)
  вместо модели для текста — Ollama отвечала на неё «400 Bad Request».
- Волна звука на плеере снова видна у обработанных записей.
- Снова открывается меню вида и сортировки медиатеки, папка подсвечивается при перетаскивании записи.
- Копирование анализа, повторная обработка, удаление записи и ещё несколько действий больше не
  обрываются без сообщения после того, как сделаны.

## 0.5.0 — English

### New
- **Several models, one text.** Each model's transcript is kept; the "Recognition" row above the text
  has the model list (✓ transcribed, ↓ not downloaded), Transcribe, Merge versions, Clear and the status.
- **Merge versions:** one text from several models — their word where they agree; the analysis model
  picks among the variants elsewhere, those places are underlined and a click shows every variant.
- Models not downloaded yet are listed in Import and Re-process and download before the processing.
- **Dictation with translation** on its own hotkey (Ctrl+Alt+T by default).
- Calendar from Outlook on this computer; checked transcripts as references; one-click library backup;
  About window; Ctrl+1/2/3 for the tabs; unused files found and freed; **Settings → Updates → Get beta versions**.

### Changed
- GigaAM / Parakeet batched on the GPU; loudness raised part by part before speech detection.
- Settings in cards; transcripts stored line by line (moved once on the first start).

### Security
- **Updates signed with the author's key**; no inline script (CSP); requests from other pages refused;
  self-installed packages checked by hash; updated certifi, requests, urllib3, idna, DOMPurify.

### Fixed
- Everything from the full audit: no lost edits, work processes end with the app, cut-off downloads are
  not "installed", calendar, ports, single instance, AltGr letters, English texts throughout.

## 0.5.0

### Новое
- **Несколько моделей — один текст.** Расшифровка каждой модели хранится отдельно: над текстом
  строка «Распознавание» со списком моделей (✓ — уже расшифровано, ↓ — модель не скачана), кнопками
  «Расшифровать», «Свести версии», «Очистить» и статусом, какой моделью сделан текст ниже.
- **Сведение версий.** Один текст из расшифровок нескольких моделей: где модели согласны — их слово,
  спорные места выбирает модель анализа (только из вариантов). Они подчёркнуты, щелчок показывает
  вариант каждой модели.
- **Нескачанные модели в списках** импорта и повторной обработки: модель скачивается перед обработкой,
  прогресс виден в строке записи.
- **Диктовка с переводом:** своя горячая клавиша (по умолчанию Ctrl+Alt+T) вставляет продиктованный
  текст на другом языке.
- **Календарь из Outlook** на этом компьютере (Microsoft 365, Exchange, Outlook.com) без ссылок и входа.
- **Проверенные расшифровки:** отметка «Проверено» делает текст эталоном для сравнения моделей.
- **Резервная копия библиотеки** одной кнопкой (база, заметки, настройки) и восстановление из неё.
- **Окно «О программе»**, Ctrl+1 / 2 / 3 для вкладок, поиск и освобождение файлов, которые не
  использует ни одна запись.
- **Бета-версии:** «Настройки → Обновления → Получать бета-версии».

### Изменено
- GigaAM и Parakeet на видеокарте распознают пакетами (быстрее); громкость поднимается по частям
  записи, поэтому тихий собеседник рядом с громким не пропадает.
- Настройки разложены по карточкам с пояснениями; горячие клавиши названы по действию.
- Расшифровки хранятся построчно в отдельной таблице: библиотека открывается быстрее, правка строки
  пишет одну строку. Перенос — один раз при первом запуске.
- Вкладка «Редактор» со своей иконкой; панели «Распознавание» и «Текст» разделены. «Удалить
  результаты» — в меню ••• записи («Очистить результаты»).

### Безопасность
- **Обновления подписаны ключом автора:** программа ставит только релиз с верной подписью.
- Страница без встроенных скриптов (CSP `script-src 'self'`); запросы других страниц отклоняются.
- Пакеты, которые программа ставит сама (yt-dlp, onnx-asr, onnxruntime-gpu), — только с проверкой хеша.
- Обновление не пишет файлы вне папки программы; восстановление копии — только в свои папки.
- Обновлены certifi, requests, urllib3, idna, DOMPurify; токен сессии не попадает в журнал и адрес.

### Исправлено
- Итог полного аудита: правки и участники не теряются при одновременных изменениях, рабочие процессы
  завершаются вместе с программой даже после сбоя, оборванные скачивания не считаются установленными,
  календарь не падает на необычных событиях, порт другой программы пропускается, один экземпляр окна,
  горячие клавиши не мешают буквам AltGr, тексты интерфейса и сообщения сервера переведены на английский.

---
