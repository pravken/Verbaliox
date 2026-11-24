# Changelog · Журнал изменений

Each release page takes its text from here, the section with its number: English first, then Russian.
Betas (`vX.Y.Z-beta.N`) show the sections of their coming version.

Описание каждой версии берётся отсюда в страницу релиза (раздел с её номером): сначала английский, затем
русский. Бета-версии (`vX.Y.Z-beta.N`) показывают раздел своей будущей версии.

## 0.9.4 — English

- **«Captions and text»** in the meeting strip while recording: the studio with the live captions and the text from any
  section.
- **The way to the studio is in the recording button**: while recording, a click on the dot, the time or the sources
  opens the studio; «Studio ›» between them and «Stop» shows whether the captions are on (a green outline while they
  are off). On the first recording a hint under it says where the captions and the text are; once closed it is not
  shown again.
- **A call is a meeting too**: while a call app (Teams, Zoom, Telegram…) or a browser holds the microphone,
  transcriptions wait, recorded or not, in the calendar or not. During a meeting a transcription starts only on the
  user's «Transcribe» and «Yes, start now».
- **A voice note is no meeting**: a recording made by hand, with no call and no meeting in the calendar, no longer
  holds the transcriptions while it records nor for the 2 minutes after it. Only a recording of a meeting (one a call
  or the calendar started, or one following a Teams meeting) holds them; the pause of 2 minutes comes only after a
  meeting.
- **The queue says what it waits for**: «A meeting is under way» or «Pause after the meeting · 1:40» with the time
  counting down, in the queue window, the strip's island, the strip and the status bar. Each transcription waiting for
  the meeting has «Start now» (after the same question as «Transcribe» during a meeting).
- **Live captions with Teams no longer jump**: a line keeps the speaker it was given, and the room for the names stays.
- **One row above the studio's text**: the tabs «Text · My notes · Questions» on the left, and on the right the chips
  «Captions» with its switch, the translation language (a menu), the memory of the caption models (a popover with the
  recognition and translation models, their size and whether they are in memory) and the gear with the rest.
- **A meeting moved or cancelled in the calendar is not reminded of at its old time**: the calendar is read afresh two
  minutes before each reminder and each meeting's start, and the reminder follows that read (a moved meeting gets its
  reminder at its new time). If the read fails, the reminder comes as before. While a meeting starts within the hour,
  the calendar is read every 5 minutes instead of 15.
- **A translation model for live captions**: the captions' models offer one model of Tencent Hy-MT3 (Apache 2.0) by the
  video card, Hy-MT3 7B (4.9 GB) on a card of 10 GB and more, else Hy-MT3 1.8B (1.3 GB); in the app's measurements
  both translate English to Russian and back more accurately than the Gemma models used so far. It is downloaded
  only on «Download» (in the popover of the caption models or in Settings → AI analysis); «Quality» then translates
  with Hy-MT3 7B (else 1.8B) and «Fast» with Hy-MT3 1.8B (else Gemma 4 E2B). Without it everything works as before.
  The 1.8B is set up in Ollama with a working chat template (the one in its file does not pass the text to the model).
- **Translation models have their own block** in Settings → AI analysis, «Translation Models (Ollama)», under the
  analysis models: both Hy-MT3 sizes (the one for this computer marked «Recommended for this computer», the other one
  can be downloaded too), with the measured time of a phrase and the video memory beside speech recognition. Two
  lists choose the model of «Quality» and «Fast» of the captions: «Auto · <the model it takes now>», the installed
  translators and the analysis models; a chosen model that is deleted gives its place to «Auto», and a model chosen in
  the studio still applies to its caption session. Dictation with translation now translates with the «Quality» model
  (Hy-MT3 when installed, with the prompt of its model card), else with the analysis model as before.
- **Translators are no longer listed as analysis models**: Hy-MT3 and a TranslateGemma installed in Ollama by hand
  cannot write an analysis and are listed with the translation models only. TranslateGemma (Gemma Terms of Use) is
  never offered for download; when installed, it is marked «Local · Gemma Terms ⚠» with «Check the license before
  commercial use», and it translates with the prompt of its model card.
- **Simpler settings, nothing hidden**: no «More» to unfold; every option is a row with a short name, a line under it
  only where the effect is not obvious, and its control at the right edge, in every section. A switch with a mode
  beside it is one list with «Off» in it (the «Recording only» mode, meeting notifications, GigaAM and Parakeet on the
  video card). The search also finds options by their former names.
- **Models leave the memory a minute after the processing**: once the queue has nothing running or waiting (a
  transcription with its automatic analysis counts as one job) and nothing uses the app for 60 seconds, the speech
  models and the analysis model are unloaded; a model asked by hand (a question to the assistant) stays for the time
  set in «Free the models from memory after». Live captions starting unload the analysis model they do not use (not
  during a running analysis), switching «Quality» ↔ «Fast» unloads the previous translation model, and the captions'
  models go a minute after the captions end. Each unload is written in the log with its reason.
- **The studio's choices stay**: «Captions» switched on or off, the translation language, «Quality / Fast», the
  caption model and the translation model are kept as settings and survive a new recording, a restart and a launch on
  another port. «Captions» is «Turn captions on when a recording starts», the caption model is «Caption model», the
  translation model is the one of the chosen mode in «Translation models»: Settings shows the same values. The models
  can be chosen before a recording too. A recording preset no longer switches the captions or the translation. With
  «Do not disturb in meetings» captions do not start by themselves on a meeting only; a voice note starts with them.

## 0.9.3 — English

- **A wrong person's name is put right with a click**: in a recording's analysis a speaker's name is a quiet
  button; its menu renames the speaker («Rename the speaker…») or puts another person in its place («This is
  someone else…», a contact or a typed name), and the analysis shows the new name at once. In a brief, a digest
  or another answer of the assistant the names of the speakers of the cited recordings are such buttons too:
  the menu lists those recordings, and the other person replaces the speaker there and the name in the answer.
- **«Mix now»**: a stopped recording whose mix waits for a meeting says which one (the calendar's meeting and its
  end) and can be mixed at once.
- **A meeting left early no longer holds the mix**: once the recording is stopped and no call app holds the
  microphone, the calendar's meeting is taken for over.
- **A brief, a digest and overviews cite whole meetings**: their marks show the meeting's date and open it, instead
  of «▶ 00:00».
- **«Open tasks from the last meeting»** in the meeting strip opens the brief with them.
- **Update check**: when GitHub limits its API (403, 60 requests an hour per address), the release is found by
  its public feed and its own files; the signature is checked as always.

### Also in 0.9.2

- **The meeting strip on top keeps its text in its place**: nothing slides under its buttons any more; the queue
  island says why jobs wait in a few words («Waiting for the meeting to end»), the whole sentence in its tooltip.
- **«recorded N min»** is shown whole; a long recording title fades at its end and scrolls to it when the pointer is
  over the strip.

### Also in 0.9.1

- **A short recording is mixed at once.** A recording of up to 3 minutes no longer waits two minutes after it ends
  for its tracks to be mixed: its mix takes seconds. A longer recording still waits for the end of the meeting
  («Don't disturb in meetings»).
- **The wait is explained.** While the mix waits, the recording says why with a countdown — «Starts in 1:40: a
  pause in case the next meeting begins right away», or «Starts after the meeting» while a call or a calendar
  meeting goes on — instead of 1 % «after the meeting».
- **A recording can be deleted while its tracks wait or are mixed.** A waiting one is deleted at once with its
  tracks; one being mixed is deleted as soon as the mix is over («The recording will be deleted as soon as its
  tracks are mixed»). No tracks are left behind, a restart meanwhile included.
- **Deleting several recordings** says why the ones left were not deleted, in the program's words, instead of «they
  may be processing».
- **The red button while recording**: only «Stop» stops; the dot, the time and the sources open the recording studio.
- **The selection bar of Recordings**: quiet actions with icons, ✕ with the count, «Delete» apart in red.

### Also in 0.9.0

- **Back and forward** at the start of the top strip, like in a browser (also Alt+← / Alt+→ and the mouse's side
  buttons).
- **The recording time** on the red button opens the recording studio; captions have one size in every window.
- **Features in their own panel**: «Manage features…» in the feature menus of Overview and Recordings and on a
  recording's feature chip opens a panel over any section; the Dictionary keeps its features card.
- **Assistant**: a greeting gets a short reply; a general question (explain a term, give advice, write a text) is
  answered by the model from what it knows, with its reasoning on and marked as not from the library; only a
  question about the recordings is answered from them, and only the cited moments are listed as sources. The
  assistant remembers the last three questions of the conversation, so «and in more detail?» works.
- **Speaker names in the analysis follow renames** even after the speakers are split again or merged: the
  analysis refers to the speaker, not to the name written at the time.
- **Windows notifications, the tray menu and meeting reminders** follow the interface language.
- The «Cherry» accent became «Raspberry», apart from the red of a recording. Menus and windows keep inside the
  program's window. Dictionary fields explain themselves.

- **A new look, «Meeting desk»**: a rail of sections on the left (Today, Overview, Recordings, Tasks, People,
  Dictionary, Assistant; Ctrl+1…6), at the bottom «Settings» and «Quit». The old sidebar is gone.
- **The meeting strip on top** says what is going on — free until the end of the day, a meeting in N minutes,
  going without recording, recording, waiting for transcription, results ready — with the button of that
  moment (Join, Record, Mark the moment, Open the results) and «＋ Import».
- **Load in the status bar**: CPU, RAM and the video memory with the program's own share; a click lists the
  models in memory, each with «Unload».
- **Today and Overview**: Today is the calendar (day, week, month; the working time gone by shaded) with the
  cards of the day; Overview is the analytics: «Statistics» tiles with a trend and the metrics of your choice,
  charts as columns, bars, a ring or a line, every part in a colour of its own.
- **My programs** (off by default): how the working time is split between programs — only the
  program's name is kept, no window titles, keys or screenshots, and it never leaves the computer.
- **Recordings**: table, cards and folders; «Columns» in every view, compact rows; search shows the places
  found in the texts; a selection bar; import from a menu, Ctrl+O or by dropping files on any screen.
- **A recording**: Transcript first, as a chat or as text; Analysis as cards with ▶ links to the moments;
  Details with «Transcribe again» and «Recreate the analysis»; a lower player that also folds into one line.
- **Tasks** as a table, cards or a calendar; **People** and **Dictionary** are sections of their own; the
  assistant shows its sources as ▶ time marks; one window after an update instead of two.
- Fixes: quitting or shutting Windows down during a transcription is no longer counted as a crash; a start
  during an update no longer rolls the installation back; the MCP server follows its setting for
  dictations at once;
  backups keep the minutes worked on this computer.
- **«Don't disturb in meetings» holds everything now**: while a meeting goes on and two minutes after it, the
  transcription, the mix of a stopped recording and the speaker models wait; Nemotron leaves memory with the
  other speech models. Models no longer load in the middle of a call and slow the computer down.
- **Live captions are off by default** and never start by themselves while «Don't disturb in meetings» holds;
  turn them on on the recording screen or in Settings → Recording.
- **Meeting hours in Overview** count every recording again, the ones not transcribed yet and cancelled included.
- **Dragging widgets** in «Customize»: the widget lifts and a slot shows where it lands.
- **Calendar month**: today is marked again.
- «Customize» names each widget instead of its internal key.
- Settings: switching tabs fades like the views.
- Interface texts in a plainer, neutral tone.
- **Analysis on the computer only**: sending text to cloud models over their API is removed. Saved API keys,
  the cloud request log and the «local only» marks are deleted; Ollama always does the analysis. Recordings
  marked «local only» before stay hidden from the agent (MCP).
- **One look for every window, menu and notice**: a head with its icon, the close button in one place, one
  button everywhere (32 px, the same corners), the side panels of Overview slide in and out; notices show
  their kind in a coloured square and the time left as a thin line.
- **Dictionary**: the words are the main card with group chips and rows like in Recordings; suggestions,
  correction and features in a column on the right from 1100 px.
- **A click on a day of the week or the month opens that day**: its meetings, the recordings made that day
  and the hours worked; ‹ › step a day.
- **Assistant**: a clear send button; the conversation title shows that it can be renamed.
- Fixes: the calendar from classic Outlook without a mail profile no longer opens Outlook's first-run wizard
  every 15 minutes; deleting an Ollama model starts Ollama when needed and deletes the name it really has;
  the shortcuts show the new icon after the next update; «About» shows the new icon.
- **Accent to choose** in Settings → General: eight colours for the picked-out buttons and marks; the
  background stays one.
- Settings fill a wide window in two columns; «Reset this tab» is gone. Today's date tile has a green frame.
  Model buttons are of one size; the agent's lines are copied with an icon in the code.
- **«Quit»** at the bottom of the rail, like the power button of Windows: «Minimize to the tray» or «Quit
  completely» (Ctrl+Q), which always asks first.
- **The queue is an island in the top strip**: nothing while nothing runs; the job with its progress ring and
  «+N queued»; a click opens the queue. The rail's «Queue» button is gone.
- **One, paler accent** for buttons, switches and the chosen segment of every switch; menus mark the current item
  in the accent instead of a tick. A second click on a menu's button closes it; Escape closes only the top layer;
  one menu at a time.
- **«＋ Import ▾»** like «● Record ▾»: the button opens everything, the menu opens the window for files, a folder or
  a link.
- **Transcript**: a recording without a text shows one card with the model choice and the progress of the mixing
  or the recognition; the model, the speakers and the tools of the text in one row.
- **My programs** counts only the minutes with input (a game controller too); the time of meetings comes from the
  recordings.
- Fixes: a question to the assistant right after the start waits for Ollama to come up; the calendar from Outlook
  never closes an Outlook in use; «Minimize to the tray» only with a tray icon;
  an update interrupted by a power loss no longer blocks the start; the strip no longer asks the calendar in a loop
  after an error; a recording opened and left quickly no longer stays hidden; widgets drag right at any interface
  scale; recordings once closed to the agent stay closed when their folder goes; the shortcuts window lists
  Ctrl+1…6.

## 0.9.2 — English

- **The meeting strip on top keeps its text in its place**: nothing slides under its buttons any more; the queue
  island says why jobs wait in a few words («Waiting for the meeting to end»), the whole sentence in its tooltip.
- **«recorded N min»** is shown whole; a long recording title fades at its end and scrolls to it when the pointer is
  over the strip.

### Also in 0.9.1

- **A short recording is mixed at once.** A recording of up to 3 minutes no longer waits two minutes after it ends
  for its tracks to be mixed: its mix takes seconds. A longer recording still waits for the end of the meeting
  («Don't disturb in meetings»).
- **The wait is explained.** While the mix waits, the recording says why with a countdown — «Starts in 1:40: a
  pause in case the next meeting begins right away», or «Starts after the meeting» while a call or a calendar
  meeting goes on — instead of 1 % «after the meeting».
- **A recording can be deleted while its tracks wait or are mixed.** A waiting one is deleted at once with its
  tracks; one being mixed is deleted as soon as the mix is over («The recording will be deleted as soon as its
  tracks are mixed»). No tracks are left behind, a restart meanwhile included.
- **Deleting several recordings** says why the ones left were not deleted, in the program's words, instead of «they
  may be processing».
- **The red button while recording**: only «Stop» stops; the dot, the time and the sources open the recording studio.
- **The selection bar of Recordings**: quiet actions with icons, ✕ with the count, «Delete» apart in red.

### Also in 0.9.0

- **Back and forward** at the start of the top strip, like in a browser (also Alt+← / Alt+→ and the mouse's side
  buttons).
- **The recording time** on the red button opens the recording studio; captions have one size in every window.
- **Features in their own panel**: «Manage features…» in the feature menus of Overview and Recordings and on a
  recording's feature chip opens a panel over any section; the Dictionary keeps its features card.
- **Assistant**: a greeting gets a short reply; a general question (explain a term, give advice, write a text) is
  answered by the model from what it knows, with its reasoning on and marked as not from the library; only a
  question about the recordings is answered from them, and only the cited moments are listed as sources. The
  assistant remembers the last three questions of the conversation, so «and in more detail?» works.
- **Speaker names in the analysis follow renames** even after the speakers are split again or merged: the
  analysis refers to the speaker, not to the name written at the time.
- **Windows notifications, the tray menu and meeting reminders** follow the interface language.
- The «Cherry» accent became «Raspberry», apart from the red of a recording. Menus and windows keep inside the
  program's window. Dictionary fields explain themselves.

- **A new look, «Meeting desk»**: a rail of sections on the left (Today, Overview, Recordings, Tasks, People,
  Dictionary, Assistant; Ctrl+1…6), at the bottom «Settings» and «Quit». The old sidebar is gone.
- **The meeting strip on top** says what is going on — free until the end of the day, a meeting in N minutes,
  going without recording, recording, waiting for transcription, results ready — with the button of that
  moment (Join, Record, Mark the moment, Open the results) and «＋ Import».
- **Load in the status bar**: CPU, RAM and the video memory with the program's own share; a click lists the
  models in memory, each with «Unload».
- **Today and Overview**: Today is the calendar (day, week, month; the working time gone by shaded) with the
  cards of the day; Overview is the analytics: «Statistics» tiles with a trend and the metrics of your choice,
  charts as columns, bars, a ring or a line, every part in a colour of its own.
- **My programs** (off by default): how the working time is split between programs — only the
  program's name is kept, no window titles, keys or screenshots, and it never leaves the computer.
- **Recordings**: table, cards and folders; «Columns» in every view, compact rows; search shows the places
  found in the texts; a selection bar; import from a menu, Ctrl+O or by dropping files on any screen.
- **A recording**: Transcript first, as a chat or as text; Analysis as cards with ▶ links to the moments;
  Details with «Transcribe again» and «Recreate the analysis»; a lower player that also folds into one line.
- **Tasks** as a table, cards or a calendar; **People** and **Dictionary** are sections of their own; the
  assistant shows its sources as ▶ time marks; one window after an update instead of two.
- Fixes: quitting or shutting Windows down during a transcription is no longer counted as a crash; a start
  during an update no longer rolls the installation back; the MCP server follows its setting for
  dictations at once;
  backups keep the minutes worked on this computer.
- **«Don't disturb in meetings» holds everything now**: while a meeting goes on and two minutes after it, the
  transcription, the mix of a stopped recording and the speaker models wait; Nemotron leaves memory with the
  other speech models. Models no longer load in the middle of a call and slow the computer down.
- **Live captions are off by default** and never start by themselves while «Don't disturb in meetings» holds;
  turn them on on the recording screen or in Settings → Recording.
- **Meeting hours in Overview** count every recording again, the ones not transcribed yet and cancelled included.
- **Dragging widgets** in «Customize»: the widget lifts and a slot shows where it lands.
- **Calendar month**: today is marked again.
- «Customize» names each widget instead of its internal key.
- Settings: switching tabs fades like the views.
- Interface texts in a plainer, neutral tone.
- **Analysis on the computer only**: sending text to cloud models over their API is removed. Saved API keys,
  the cloud request log and the «local only» marks are deleted; Ollama always does the analysis. Recordings
  marked «local only» before stay hidden from the agent (MCP).
- **One look for every window, menu and notice**: a head with its icon, the close button in one place, one
  button everywhere (32 px, the same corners), the side panels of Overview slide in and out; notices show
  their kind in a coloured square and the time left as a thin line.
- **Dictionary**: the words are the main card with group chips and rows like in Recordings; suggestions,
  correction and features in a column on the right from 1100 px.
- **A click on a day of the week or the month opens that day**: its meetings, the recordings made that day
  and the hours worked; ‹ › step a day.
- **Assistant**: a clear send button; the conversation title shows that it can be renamed.
- Fixes: the calendar from classic Outlook without a mail profile no longer opens Outlook's first-run wizard
  every 15 minutes; deleting an Ollama model starts Ollama when needed and deletes the name it really has;
  the shortcuts show the new icon after the next update; «About» shows the new icon.
- **Accent to choose** in Settings → General: eight colours for the picked-out buttons and marks; the
  background stays one.
- Settings fill a wide window in two columns; «Reset this tab» is gone. Today's date tile has a green frame.
  Model buttons are of one size; the agent's lines are copied with an icon in the code.
- **«Quit»** at the bottom of the rail, like the power button of Windows: «Minimize to the tray» or «Quit
  completely» (Ctrl+Q), which always asks first.
- **The queue is an island in the top strip**: nothing while nothing runs; the job with its progress ring and
  «+N queued»; a click opens the queue. The rail's «Queue» button is gone.
- **One, paler accent** for buttons, switches and the chosen segment of every switch; menus mark the current item
  in the accent instead of a tick. A second click on a menu's button closes it; Escape closes only the top layer;
  one menu at a time.
- **«＋ Import ▾»** like «● Record ▾»: the button opens everything, the menu opens the window for files, a folder or
  a link.
- **Transcript**: a recording without a text shows one card with the model choice and the progress of the mixing
  or the recognition; the model, the speakers and the tools of the text in one row.
- **My programs** counts only the minutes with input (a game controller too); the time of meetings comes from the
  recordings.
- Fixes: a question to the assistant right after the start waits for Ollama to come up; the calendar from Outlook
  never closes an Outlook in use; «Minimize to the tray» only with a tray icon;
  an update interrupted by a power loss no longer blocks the start; the strip no longer asks the calendar in a loop
  after an error; a recording opened and left quickly no longer stays hidden; widgets drag right at any interface
  scale; recordings once closed to the agent stay closed when their folder goes; the shortcuts window lists
  Ctrl+1…6.

## 0.9.1 — English

- **A short recording is mixed at once.** A recording of up to 3 minutes no longer waits two minutes after it ends
  for its tracks to be mixed: its mix takes seconds. A longer recording still waits for the end of the meeting
  («Don't disturb in meetings»).
- **The wait is explained.** While the mix waits, the recording says why with a countdown — «Starts in 1:40: a
  pause in case the next meeting begins right away», or «Starts after the meeting» while a call or a calendar
  meeting goes on — instead of 1 % «after the meeting».
- **A recording can be deleted while its tracks wait or are mixed.** A waiting one is deleted at once with its
  tracks; one being mixed is deleted as soon as the mix is over («The recording will be deleted as soon as its
  tracks are mixed»). No tracks are left behind, a restart meanwhile included.
- **Deleting several recordings** says why the ones left were not deleted, in the program's words, instead of «they
  may be processing».
- **The red button while recording**: only «Stop» stops; the dot, the time and the sources open the recording studio.
- **The selection bar of Recordings**: quiet actions with icons, ✕ with the count, «Delete» apart in red.

### Also in 0.9.0

- **Back and forward** at the start of the top strip, like in a browser (also Alt+← / Alt+→ and the mouse's side
  buttons).
- **The recording time** on the red button opens the recording studio; captions have one size in every window.
- **Features in their own panel**: «Manage features…» in the feature menus of Overview and Recordings and on a
  recording's feature chip opens a panel over any section; the Dictionary keeps its features card.
- **Assistant**: a greeting gets a short reply; a general question (explain a term, give advice, write a text) is
  answered by the model from what it knows, with its reasoning on and marked as not from the library; only a
  question about the recordings is answered from them, and only the cited moments are listed as sources. The
  assistant remembers the last three questions of the conversation, so «and in more detail?» works.
- **Speaker names in the analysis follow renames** even after the speakers are split again or merged: the
  analysis refers to the speaker, not to the name written at the time.
- **Windows notifications, the tray menu and meeting reminders** follow the interface language.
- The «Cherry» accent became «Raspberry», apart from the red of a recording. Menus and windows keep inside the
  program's window. Dictionary fields explain themselves.

- **A new look, «Meeting desk»**: a rail of sections on the left (Today, Overview, Recordings, Tasks, People,
  Dictionary, Assistant; Ctrl+1…6), at the bottom «Settings» and «Quit». The old sidebar is gone.
- **The meeting strip on top** says what is going on — free until the end of the day, a meeting in N minutes,
  going without recording, recording, waiting for transcription, results ready — with the button of that
  moment (Join, Record, Mark the moment, Open the results) and «＋ Import».
- **Load in the status bar**: CPU, RAM and the video memory with the program's own share; a click lists the
  models in memory, each with «Unload».
- **Today and Overview**: Today is the calendar (day, week, month; the working time gone by shaded) with the
  cards of the day; Overview is the analytics: «Statistics» tiles with a trend and the metrics of your choice,
  charts as columns, bars, a ring or a line, every part in a colour of its own.
- **My programs** (off by default): how the working time is split between programs — only the
  program's name is kept, no window titles, keys or screenshots, and it never leaves the computer.
- **Recordings**: table, cards and folders; «Columns» in every view, compact rows; search shows the places
  found in the texts; a selection bar; import from a menu, Ctrl+O or by dropping files on any screen.
- **A recording**: Transcript first, as a chat or as text; Analysis as cards with ▶ links to the moments;
  Details with «Transcribe again» and «Recreate the analysis»; a lower player that also folds into one line.
- **Tasks** as a table, cards or a calendar; **People** and **Dictionary** are sections of their own; the
  assistant shows its sources as ▶ time marks; one window after an update instead of two.
- Fixes: quitting or shutting Windows down during a transcription is no longer counted as a crash; a start
  during an update no longer rolls the installation back; the MCP server follows its setting for
  dictations at once;
  backups keep the minutes worked on this computer.
- **«Don't disturb in meetings» holds everything now**: while a meeting goes on and two minutes after it, the
  transcription, the mix of a stopped recording and the speaker models wait; Nemotron leaves memory with the
  other speech models. Models no longer load in the middle of a call and slow the computer down.
- **Live captions are off by default** and never start by themselves while «Don't disturb in meetings» holds;
  turn them on on the recording screen or in Settings → Recording.
- **Meeting hours in Overview** count every recording again, the ones not transcribed yet and cancelled included.
- **Dragging widgets** in «Customize»: the widget lifts and a slot shows where it lands.
- **Calendar month**: today is marked again.
- «Customize» names each widget instead of its internal key.
- Settings: switching tabs fades like the views.
- Interface texts in a plainer, neutral tone.
- **Analysis on the computer only**: sending text to cloud models over their API is removed. Saved API keys,
  the cloud request log and the «local only» marks are deleted; Ollama always does the analysis. Recordings
  marked «local only» before stay hidden from the agent (MCP).
- **One look for every window, menu and notice**: a head with its icon, the close button in one place, one
  button everywhere (32 px, the same corners), the side panels of Overview slide in and out; notices show
  their kind in a coloured square and the time left as a thin line.
- **Dictionary**: the words are the main card with group chips and rows like in Recordings; suggestions,
  correction and features in a column on the right from 1100 px.
- **A click on a day of the week or the month opens that day**: its meetings, the recordings made that day
  and the hours worked; ‹ › step a day.
- **Assistant**: a clear send button; the conversation title shows that it can be renamed.
- Fixes: the calendar from classic Outlook without a mail profile no longer opens Outlook's first-run wizard
  every 15 minutes; deleting an Ollama model starts Ollama when needed and deletes the name it really has;
  the shortcuts show the new icon after the next update; «About» shows the new icon.
- **Accent to choose** in Settings → General: eight colours for the picked-out buttons and marks; the
  background stays one.
- Settings fill a wide window in two columns; «Reset this tab» is gone. Today's date tile has a green frame.
  Model buttons are of one size; the agent's lines are copied with an icon in the code.
- **«Quit»** at the bottom of the rail, like the power button of Windows: «Minimize to the tray» or «Quit
  completely» (Ctrl+Q), which always asks first.
- **The queue is an island in the top strip**: nothing while nothing runs; the job with its progress ring and
  «+N queued»; a click opens the queue. The rail's «Queue» button is gone.
- **One, paler accent** for buttons, switches and the chosen segment of every switch; menus mark the current item
  in the accent instead of a tick. A second click on a menu's button closes it; Escape closes only the top layer;
  one menu at a time.
- **«＋ Import ▾»** like «● Record ▾»: the button opens everything, the menu opens the window for files, a folder or
  a link.
- **Transcript**: a recording without a text shows one card with the model choice and the progress of the mixing
  or the recognition; the model, the speakers and the tools of the text in one row.
- **My programs** counts only the minutes with input (a game controller too); the time of meetings comes from the
  recordings.
- Fixes: a question to the assistant right after the start waits for Ollama to come up; the calendar from Outlook
  never closes an Outlook in use; «Minimize to the tray» only with a tray icon;
  an update interrupted by a power loss no longer blocks the start; the strip no longer asks the calendar in a loop
  after an error; a recording opened and left quickly no longer stays hidden; widgets drag right at any interface
  scale; recordings once closed to the agent stay closed when their folder goes; the shortcuts window lists
  Ctrl+1…6.

## 0.9.0 — English

- **Back and forward** at the start of the top strip, like in a browser (also Alt+← / Alt+→ and the mouse's side
  buttons).
- **The recording time** on the red button opens the recording studio; captions have one size in every window.
- **Features in their own panel**: «Manage features…» in the feature menus of Overview and Recordings and on a
  recording's feature chip opens a panel over any section; the Dictionary keeps its features card.
- **Assistant**: a greeting gets a short reply; a general question (explain a term, give advice, write a text) is
  answered by the model from what it knows, with its reasoning on and marked as not from the library; only a
  question about the recordings is answered from them, and only the cited moments are listed as sources. The
  assistant remembers the last three questions of the conversation, so «and in more detail?» works.
- **Speaker names in the analysis follow renames** even after the speakers are split again or merged: the
  analysis refers to the speaker, not to the name written at the time.
- **Windows notifications, the tray menu and meeting reminders** follow the interface language.
- The «Cherry» accent became «Raspberry», apart from the red of a recording. Menus and windows keep inside the
  program's window. Dictionary fields explain themselves.

- **A new look, «Meeting desk»**: a rail of sections on the left (Today, Overview, Recordings, Tasks, People,
  Dictionary, Assistant; Ctrl+1…6), at the bottom «Settings» and «Quit». The old sidebar is gone.
- **The meeting strip on top** says what is going on — free until the end of the day, a meeting in N minutes,
  going without recording, recording, waiting for transcription, results ready — with the button of that
  moment (Join, Record, Mark the moment, Open the results) and «＋ Import».
- **Load in the status bar**: CPU, RAM and the video memory with the program's own share; a click lists the
  models in memory, each with «Unload».
- **Today and Overview**: Today is the calendar (day, week, month; the working time gone by shaded) with the
  cards of the day; Overview is the analytics: «Statistics» tiles with a trend and the metrics of your choice,
  charts as columns, bars, a ring or a line, every part in a colour of its own.
- **My programs** (off by default): how the working time is split between programs — only the
  program's name is kept, no window titles, keys or screenshots, and it never leaves the computer.
- **Recordings**: table, cards and folders; «Columns» in every view, compact rows; search shows the places
  found in the texts; a selection bar; import from a menu, Ctrl+O or by dropping files on any screen.
- **A recording**: Transcript first, as a chat or as text; Analysis as cards with ▶ links to the moments;
  Details with «Transcribe again» and «Recreate the analysis»; a lower player that also folds into one line.
- **Tasks** as a table, cards or a calendar; **People** and **Dictionary** are sections of their own; the
  assistant shows its sources as ▶ time marks; one window after an update instead of two.
- Fixes: quitting or shutting Windows down during a transcription is no longer counted as a crash; a start
  during an update no longer rolls the installation back; the MCP server follows its setting for
  dictations at once;
  backups keep the minutes worked on this computer.
- **«Don't disturb in meetings» holds everything now**: while a meeting goes on and two minutes after it, the
  transcription, the mix of a stopped recording and the speaker models wait; Nemotron leaves memory with the
  other speech models. Models no longer load in the middle of a call and slow the computer down.
- **Live captions are off by default** and never start by themselves while «Don't disturb in meetings» holds;
  turn them on on the recording screen or in Settings → Recording.
- **Meeting hours in Overview** count every recording again, the ones not transcribed yet and cancelled included.
- **Dragging widgets** in «Customize»: the widget lifts and a slot shows where it lands.
- **Calendar month**: today is marked again.
- «Customize» names each widget instead of its internal key.
- Settings: switching tabs fades like the views.
- Interface texts in a plainer, neutral tone.
- **Analysis on the computer only**: sending text to cloud models over their API is removed. Saved API keys,
  the cloud request log and the «local only» marks are deleted; Ollama always does the analysis. Recordings
  marked «local only» before stay hidden from the agent (MCP).
- **One look for every window, menu and notice**: a head with its icon, the close button in one place, one
  button everywhere (32 px, the same corners), the side panels of Overview slide in and out; notices show
  their kind in a coloured square and the time left as a thin line.
- **Dictionary**: the words are the main card with group chips and rows like in Recordings; suggestions,
  correction and features in a column on the right from 1100 px.
- **A click on a day of the week or the month opens that day**: its meetings, the recordings made that day
  and the hours worked; ‹ › step a day.
- **Assistant**: a clear send button; the conversation title shows that it can be renamed.
- Fixes: the calendar from classic Outlook without a mail profile no longer opens Outlook's first-run wizard
  every 15 minutes; deleting an Ollama model starts Ollama when needed and deletes the name it really has;
  the shortcuts show the new icon after the next update; «About» shows the new icon.
- **Accent to choose** in Settings → General: eight colours for the picked-out buttons and marks; the
  background stays one.
- Settings fill a wide window in two columns; «Reset this tab» is gone. Today's date tile has a green frame.
  Model buttons are of one size; the agent's lines are copied with an icon in the code.
- **«Quit»** at the bottom of the rail, like the power button of Windows: «Minimize to the tray» or «Quit
  completely» (Ctrl+Q), which always asks first.
- **The queue is an island in the top strip**: nothing while nothing runs; the job with its progress ring and
  «+N queued»; a click opens the queue. The rail's «Queue» button is gone.
- **One, paler accent** for buttons, switches and the chosen segment of every switch; menus mark the current item
  in the accent instead of a tick. A second click on a menu's button closes it; Escape closes only the top layer;
  one menu at a time.
- **«＋ Import ▾»** like «● Record ▾»: the button opens everything, the menu opens the window for files, a folder or
  a link.
- **Transcript**: a recording without a text shows one card with the model choice and the progress of the mixing
  or the recognition; the model, the speakers and the tools of the text in one row.
- **My programs** counts only the minutes with input (a game controller too); the time of meetings comes from the
  recordings.
- Fixes: a question to the assistant right after the start waits for Ollama to come up; the calendar from Outlook
  never closes an Outlook in use; «Minimize to the tray» only with a tray icon;
  an update interrupted by a power loss no longer blocks the start; the strip no longer asks the calendar in a loop
  after an error; a recording opened and left quickly no longer stays hidden; widgets drag right at any interface
  scale; recordings once closed to the agent stay closed when their folder goes; the shortcuts window lists
  Ctrl+1…6.

## 0.8.25 — English

- **Join a meeting from the notification**: when a meeting starts, a Windows notification with
  «Join» opens its call (Teams in its app, Zoom, Google Meet, Webex — the link from the invitation); it stays
  until answered. The reminder ahead comes when you choose: 30 seconds to 15 minutes before, or not at all.
  On Home a meeting about to start has «Join».
- **Public holidays of your country**: Settings → Calendar → Holidays, a country (about 250) and its region;
  asked at the first start and after this update. **Your own days off and vacations** there and right in the
  calendar (a day's «⋯» or a right click). Days off are hatched and are no working days on Home.
- **How long the working day lasted**: the time at the computer (keyboard and mouse, a recording, a call),
  like the Teams status; the «Working day» widget, the hours of each day in the calendar, and a reminder
  after 8 hours (or as set). Only on this computer, can be turned off.
- **The card of a feature**, from the «Features» widget on Home: its next meeting with «Join», what changed in
  a week, «Where we are» from the analysis model on a click, its weeks, people, decisions, tasks and meetings.
- **What's new after an update**: a small window with the new settings and features, shown once.
- **The recognition row is one line**: «Version: … ▾», «Transcribe again», «⋯» and when the text was made.
- **Home** (was «Dashboard»): one look, steel blue on cold slate; the views framed together at the top; widgets
  fill their rows; the period's progress in calendar or working days; the week's cards keep words whole.
- A calendar event can be «no meeting» (one or the whole series); long blocks and unrecorded meetings are not
  counted as going on.
- Obsidian: a note follows its recording's features and title.
- Smooth switching between tabs and views.
- **Fixes from a code audit**: a recording recovered after a crash is no longer deleted at the same start,
  and a crash during the mix recovers it whole with its notes; a recording is dated by its start, not by
  «Stop»; a restore replaces a damaged database; a broken answer of the model no longer deletes the tasks;
  calendar series keep their last meeting and 29 February; Settings keep what is being typed; Esc closes the
  cloud log and the template windows; the agent (MCP) gets nothing when the local-only list cannot be read.
- **Faster on a big library**: editing lines of a transcript, search, Home, the calendar day and the people
  list take a fraction of the time; the library list is not downloaded again while nothing changed, nor while
  the window is hidden.
- **More fixes from the audit**: cancelling one job of a recording no longer cancels the next one; a job
  interrupted twice at startup stops instead of resuming forever; the Obsidian note is written whole and a
  rename keeps your section; a damaged transcript version no longer breaks the recording; due dates read
  weekdays as whole words; calendar series in UTC keep their times; a restore drops stale thumbnails and keeps
  only the last 3 old databases; features find meetings by word forms («платежам» for «Платежи»); a closed
  feature card stays closed; the template editor asks before dropping edits; the interface language is kept
  whatever port the app starts on; the update rollback checks file hashes, uv is pinned and checked, the app
  window opens by a one-time address.

## 0.8.24 — English

- **The next meeting in sight**: under the greeting a card «Next in 12 min · title» (orange in its last 5
  minutes, «on · 25 min left» during it) with the day's counts; «→ 12 min» on the week's «now».
- **New widgets**: «Before the meeting» (who, when, what is open from the last meetings, the brief),
  «Due today», «Free time» (windows of 30 min or more), «Load of the week» (hours a day against your norm),
  «Series giving nothing».
- **Themes**: Settings → General → Appearance — the accent colour and the background from presets.
- The period's progress next to its dates; the date tile opens this week's calendar; the week shows whole
  titles; a point for fractions.
- The time on the dashboard follows by itself, also after the window is restored; «In a minute: …» goes
  once the recording is on.
- **Obsidian notes in date folders**: with «Folders by date» on, the notes go into their date's folders, the
  ones made before move by themselves (the tray shows it) and come back when it is off.
- «Auto-import folder» is now «Auto-import folder for audio and video».

## 0.8.23 — English

- **One red button for recording**: its ▾ menu records with a preset, with captions and translation, starts
  the dictation and opens the recording settings. The «Studio» tab and the dashboard's big buttons are gone;
  the recording's screen shows in the bar only while it records, with the text, the notes and the people.
- **The transcript starts right under the title**: the recognition is one button «versions and actions ▾»,
  the chapters are on the player's wave only, «No fillers» and «Auto-scroll» are in the view menu.
- **Analysis**: three buttons over a section — «Regenerate», «Copy», «⋯»; the export, the overview's
  settings, the doubtful words and the question about the recording are in «⋯».
- **Dashboard details**: decisions grouped by meeting, quieter rows; the period's numbers on one line.

## 0.8.22 — English

- **Agent access (MCP) on Windows**: the Russian text no longer comes to the agent as «�», and a search in
  Russian finds the meetings (the server now talks UTF-8 whatever the system's code page).

## 0.8.21 — English

- **Dashboard details**: every number and widget opens a panel with what it is made of — the meetings of
  the period (decisions, tasks, how much you spoke, hours by feature), every decision, your tasks, a person
  (meetings together, who owes whom).
- **«Waiting on others»**: a widget and a list of what others promised you, how many days it has been open.
- **Meetings without outcome**: no decision and no task, you hardly spoke, a series giving nothing — counted
  on the dashboard and filtered in the list of meetings.
- **Agent access (MCP)**: Claude or another agent searches your meetings and reads their sections, decisions
  and tasks itself; read only, the «local only» recordings are not given. Settings → Export has the lines for
  Claude Desktop and Claude Code.
- **«Digest (~5 min)»** in the export menu: the moments of the decisions and tasks and the starts of the
  chapters in one file, made from the analysis.
- **Tasks read better**: the second look at each task writes it as one clear action or drops it.
- **The queue**: «Pause» / «Resume» and «Cancel all»; a waiting job of any kind can be cancelled at once.
- **Two modes**: «Do not disturb in meetings» (the analysis waits only during a meeting) and «Recording only»
  (everywhere until off, or for 30 min – the rest of the day), both in the tray menu; the tray menu is short.
- **Mouse back / forward buttons** move between the places of the app instead of the loading page.

## 0.8.20 — English

- **Dashboard: the time already past is filled.** Today: the scale up to «now», a thicker line with the time,
  a tick on the meetings over, the one going on in red with how far it is and the minutes left. Week: the days
  past filled whole, today down to a line with the time after the last thing already begun.
- **Choosing a feature of a recording**: a click chooses and closes the list, the feature lights up in the
  header; in the list the recording's features are framed and ticked.
- **Obsidian: «Re-export all transcripts»** — all recordings or only those without a note, and «Complete what
  is missing»: where a transcript has no overview, tasks or chapters, the analysis model writes them (in the
  queue, one at a time, not during meetings) and the note is saved again.
- **Models panel**: a loaded model (gemma) no longer shows 0.5 GB; never less than the size of its file.

## 0.8.19 — English

- **The automatic analysis runs again** after a transcription: Ollama now stops with the app, and a stopped
  Ollama was taken for «no analysis model». It is started when a model is downloaded.
- **Analysis only when there is no meeting**: while the app records or the calendar has a meeting, the analysis
  does not start; one already running stops and its model is unloaded, so the computer does not slow down. The
  recordings are analysed by themselves two minutes after the meeting (Settings → After transcription).
- **Economy mode (recording only)** in the tray icon's menu and Settings → General: the models are unloaded,
  transcription, analysis and live captions wait; the status bar shows it and turns it off with a click.
- **Less load on the processor**: GigaAM and Parakeet on the processor use half of the cores (2 to 8) instead
  of all of them; the number can be set. «Turn captions on when a recording starts» can be switched off; the
  Teams captions are saved with the recording either way. GigaAM and Parakeet can each be set to the processor.
- **Obsidian: everything in the note** — the transcript, overview, tasks, chapters, decisions, letter, notes,
  your own templates and answers, added whenever something new is made. A contents line with links, times in
  the chapters that open the transcript line, a «Participants» section (who spoke how much, longest monologues,
  interruptions), and marks around every section for agents (`<!-- verbaliox:tasks:start -->`, listed in the
  note's properties). «Save all recordings», and turning auto-export on writes the notes of earlier recordings.
- **A call during a calendar meeting** is no longer named after it: the people heard, the title and the call's
  app are compared with the event; another person's call is named «Call: Name».
- **A reminder of recordings whose transcription was cancelled**, on the dashboard («Transcribe all», «Don't
  remind») and once a day as a notification, never during a meeting.

## 0.8.18 — English

- **Dashboard instead of «Today» and «Tasks»**, the first page of the app: the date and greeting, the period
  (week, month, quarter) and a feature filter; widgets for the numbers of the period, today's meetings with
  auto-recording, the week, my tasks, features with eight weeks of activity, time in meetings, the people met
  most, the decisions of the analyses, a summary of the period by the local model, recent recordings and what is
  being processed. «Customize» drags, sizes (S · M · L · W), removes and adds widgets; the set is kept on this
  computer. Only my own tasks are counted («This is me»); other people's stay on the Tasks page.
- **Obsidian: notes in feature folders** (on by default) and {feature} in the file name template; the note
  moves when the feature changes; features in the note's properties and as a tag.
- **Recording**: a round red button at the right of the top bar; while recording it shows the time and «Stop».

## 0.8.17 — English

- **Memory left to the system** (Settings → General): RAM and video memory the app and its models do not take,
  «Auto» by the computer (RAM: 2 GB at 8, 4 at 16, 6 at 32, 8 above; video memory 0.5 GB, 1 GB on cards of
  12 GB and more). Ollama and the work processes are capped at the rest, Ollama keeps the card's reserve free,
  idle models are unloaded when free memory runs short; a model that does not fit says so in words.
- **Names in the analysis follow**: a participant renamed in a recording, or a contact's name put right, is
  written anew in the analyses and tasks, in the right case («Ярослава Мельника» → «Ярослава Мельникова»).
- **«This is someone else…»** on a person in the analysis: every mention and the recording's tasks go to the
  participant or contact chosen (with «Undo»).
- **A dictionary word can be edited**: the word, its variants and category («Edit» or a double click).
- **The «Analysis» tab shows the analysis running**: its mark turns and a dot pulses.
- **Recording**: no false «the computer's sound is not heard» after a call watched in another window; the
  voice cleanup after a long call shows the time it has taken (and its share from the second time on).

## 0.8.16 — English

- **One person, one block of text**: replies of the same person in a row are no longer split into lines with the
  name repeated. The name and the time are shown once and the phrases run on as one text; a long block is split
  into paragraphs after a pause in the speech or once a paragraph runs long, each with its time on the left.
  Each phrase can still be edited (the pencil on hover or a double click), playback lights the current phrase,
  a click on a word seeks. The person of a whole block is changed in its header; of one phrase, with a right
  click «This phrase was said by…», where «Edit phrase» and «Join with the previous phrase» are too.

## 0.8.15 — English

- **The library as a table on the whole window**, like the columns of Windows Explorer: the button beside
  «Library» opens it. Name, feature, date, length, participants, language and status; date added, file size,
  recognition model, open tasks and folder on request («Columns», with «Restore defaults»). A click on a header
  sorts, the edge of a header sets the width; groups by day, feature or folder; search and a feature filter.
  A click picks (Ctrl and Shift for several), a double click or Enter opens, a right click is the recording's
  menu, a row dragged goes into a folder.
- **The feature in the library**: its colour and name beside the title of a recording; in the compact list a
  coloured dot in the same place on every row.
- **A downloaded analysis model no longer reads as not downloaded** after a restart: while Ollama is stopped
  its models are read from its folder, and analysis starts it by itself.

## 0.8.14 — English

- **Contacts**: a button in the sidebar opens everyone the program knows. A person's card shows their open
  tasks (each can be reassigned there), the recordings they speak in, are named in or were invited to, and
  «+ Task». The analysis and the task search are told of the contacts, not only of the participants.
- **Every person named is marked** in the analysis and the tasks: a contact is a link to their card; an unclear
  name is offered a contact, as a feature is («Dmitry Orlov?» with ✓ and ✕); a name not in the contacts can be
  added or said to be someone; a name the transcript does not have at all is red, the model may have made it up.
- **Full names**: the model writes people as in the contacts, not «Дима»; a confirmed short form is written out
  in the recording's analysis.
- **Fewer doubtful words**: no common words («и», «в», «что»), no other endings, nothing every model heard alike
  elsewhere; a button hides the underlines.
- **New versions are told**: a Windows notification, a mark in the sidebar until installed, what is new before
  and once after the update.
- **Recording**: a chime a minute before a meeting is recorded by itself, at the start and after the stop (not in
  the recording; Settings → Recording); a calendar recording stops when the call ends before its time.
- **The day on the home page**: meetings at the same time stand side by side, their shared time hatched; full
  titles on hover.
- **The dictionary** opens in its own window; **the models panel** chooses after how long an idle model is
  unloaded, its timer stays on one line.

## 0.8.13 — English

- **The first start, one topic a step**: the AI analysis; the sound (microphone and computer sound, the
  microphone only or the computer only, the microphone with a level check, the noise filter); calls
  recorded by themselves with the apps to watch and Teams captions (Windows); the calendar (Outlook or a
  link) and recording every meeting in it; then what downloads, with the precise mode and «Start with
  Windows». A calendar address the server refuses no longer loses the other choices.
- **The precise mode takes every speech model**, and its list shows each model on its own line with its
  state and «Download» beside one not downloaded yet.
- **Analysis models: only Gemma 4 E4B and Gemma 4 E2B are offered.** In the measurements on real meetings
  one of the two finds more tasks, faster and in less memory than Qwen3.5 4B, Qwen3 8B, Qwen3 14B and Qwen
  Lite. A Qwen already downloaded stays in the list and keeps working. With no model chosen, Gemma 4 E2B
  is used.
- **Model cards**: the size, the license and the scores stay in sight; the description opens under «i» or
  with a click on the card. The descriptions say what each model is and what it was measured at. The
  scores (accuracy, quality, speed, load) follow the measurements, half a dot a step, so no two models tie.
- **The models panel**: one model per line (no flicker under the cursor), the legend under «i», a solid
  background.
- With a cloud model the local ones are named «for translation and dubbing», which always run on this
  computer.
- **The GPU build of ONNX Runtime**: a file the antivirus holds while it is renamed no longer fails the
  install (WinError 5); the program uses the new folder and finishes the swap at the next start.
- Settings: «For advanced users» is now «Experimental».

## 0.8.12 — English

- **The first start**: the window no longer crashes while WebView2 makes its profile (the server now
  starts once the window is ready); the tray icon and «Start with Windows» work from the first start.
- **Setup uses the Python it downloaded**: when Windows refuses the link uv makes inside the program
  folder, the environment is made from that Python directly instead of the system's.
- **The setup window**: Ollama found shows a green dot; missing, a dark check box (the whole row ticks it)
  instead of a white square.

## 0.8.11 — English

- **The analysis in steps** (on by default, Settings → AI analysis): the decisions and open questions
  first, then the tasks from the whole transcript, then the protocol. Its decisions, open questions and
  next steps are those lists word for word, so the overview and the tasks always agree. A task found later
  (the tasks found again on their own) is added to the protocol's next steps. Measured on 8 reference
  recordings: as many tasks found and more of them right, no disagreement, about 12 s more on an hour.
- **Correct the analysis by hand**: select a word → «Correct…» puts it right in every section of the
  recording; «Edit» opens a section as Markdown. The right spelling goes to the dictionary with the wrong
  one as its variant, so recognition and the next analyses write it right.
- **Doubtful words are underlined** in the analysis: where the recognition models heard differently or
  Whisper was unsure. A click offers the other spelling, the place in the recording or «Correct as it is».
  «Check the words with a model» (⋯) has a small local model look for terms and names heard wrong.
- **Faster and whole on long recordings**: the notes of a long recording's parts are written without
  reasoning, and with a card of 8 GB or more an answer has twice the room — no answer cut and asked again.
- An English meeting gets its tasks in English and calls unnamed speakers «Speaker N».
- The «Next steps» tab, which repeated the tasks, is gone (kept where one was made).
- Settings: «Ask before in-person meetings» can always be switched; a note says it works with recording
  all meetings.
- **Ollama no longer stays in memory after the app closes**: the Ollama the app started ends with it (on a
  crash too); an Ollama you started yourself keeps running but lets go of the models.
- **Remove everything**: `uninstall.bat` in the program folder («Remove Verbaliox completely» in the Start
  menu) removes the program, its data, models, autostart, shortcuts and temporary files, for a portable
  folder and an installed copy alike. Ollama, uv and Python are asked about separately; folders you chose
  (recordings elsewhere, exports, Obsidian) stay.

## 0.8.10 — English

- **One context for every tab of a recording's analysis**: the tasks are told the protocol's decisions and
  next steps (a decision that is an action becomes a task, when it was said in the transcript); the
  protocol and the other tabs (the short summary, the follow-up email, your notes, your templates) are
  told the tasks found, and the other tabs the protocol's decisions, open questions and next steps.
  Already analysed recordings change after «Recreate».

## 0.8.9 — English

- **Update a git clone from the app**: «Update via git» in Settings → General → Updates runs update.bat
  (the new version and the packages it needs) and the app closes for it, then starts again.
- **The protocol puts the result first**: summary, decisions, the new «Open questions», next steps, then
  the discussion grouped by topic and the details mentioned.
- **Today** keeps the working day you chose: an all-day or long event no longer shows the night from 00:00;
  a meeting a little past the edges stretches it by two hours at most.
- **Tasks page**: rows wrap by the list's own width (with the summary open beside it the text ran under the
  assignee); tasks the model gave to «team» or «none» are on nobody.

## 0.8.8 — English

- **Import without recognition**: «Only add, without recognition» in the import window puts the files
  (or a link's download) in the library; «Transcribe» on the recording starts it when the text is needed.
- **The precise mode in the import window**, under the speech model, not behind «Change»; turned on in
  Settings with nothing ticked, it ticks GigaAM v3, Whisper Pro and Parakeet TDT v3; its text says what
  «the main model» is.
- **A disputed word says who picked it**: the analysis model by the words around it, or the most
  accurate model when the analysis model did not decide.
- **The Models panel**: a running model shows the minutes until it unloads by itself; on hover a chip
  says what a click does («Unload ×» in red, «Start ▷»).
- **Features**: the recording's header shows them at the right, in one place, after «Feature:»; the
  picker stays under them after a feature is made; the library has a button of its own for them beside
  the filters.
- **Task cards**: «Assignee» before the name, «for» before the person a task is for.
- **Live captions**: the fast mode uses Gemma 4 E2B (measured on en↔ru: near E4B in quality at ~0.4 s a
  phrase); models not free for commercial use are no longer picked.
- Dark checkboxes everywhere; no blue dots on the Settings sections; a softer dialog shadow; a list's
  focus ring is no longer cut; «Dubbing environment works» is a green notice, not a red error.

## 0.8.7 — English

- **Features**: tag a meeting with the feature it is about (one or a few). A series can tag its new
  meetings by itself; the meeting's Teams title and the analysis model suggest a feature (✓ / ✕). The
  library and the Tasks page filter and group by feature; a feature's page gathers its meetings, their
  decisions and its open tasks, with the assistant on them. Settings → Dictionary → Features: a colour,
  a description, keywords and terms (they help recognition and the models).
- **The organizer's MFU**: paste the follow-up from the Teams chat into a recording; its tasks are taken
  as written and the protocol leans on it. Each task card shows where it came from: MFU, LLM or ✎.
- **Tasks as cards**: the person and the due date open their pickers; a short name said in the meeting
  («Макс», «Дима») finds the participant written in full in Teams, a misspelt name is the participant's.
- **Gemma 4** is the default analysis model (E4B on 8 GB cards and more, E2B below), reading 32k of
  context at once on 8 GB cards; it shares the card with speech recognition. The app says when Ollama
  needs updating for it.
- **Nemotron 3 Diarization** (NVIDIA, OpenMDW-1.1) as a choice for telling speakers apart; a number of
  speakers said in advance is kept better.
- **Cloud analysis works with the current models**: Claude, the new OpenAI models and Gemini get
  requests they accept; a cut, filtered or refused answer is said instead of saved; a retired model is
  replaced by one of its family; every send is in the privacy log. Gemini on a free key may not finish
  the protocol of an hour's meeting in the 10 minutes the app waits.
- **A task can go to anyone of «Everyone»** (the people directory), not only to the meeting's people;
  typing narrows the list. A name variant merged in the directory («Лёля» to «Ольга Смирнова») finds
  its person in the tasks the model finds.
- **Nemotron**: in Auto a group of scraps (a few seconds in a long recording) is no longer a person;
  on the video card it runs in bf16, faster and in less memory.
- **Settings fit a narrow window**: the sections become a column of icons, the fields go one under another.
- **The glossary** holds about a hundred terms a feature and does not repeat the meeting's feature
  terms; the transcript's room counts the feature's note and the glossary. The Models panel shows the
  real size of a loaded Gemma 4.

- **Settings in 7 tabs instead of 14**: the former tabs are sections (Updates and About in General,
  Hotkeys and Calendar in Recording, Speech models and Dictionary in Recognition, Model comparison and
  Dubbing in Advanced). Old links open the right section.
- **A brief before the meeting.** On Today a meeting that continues a series shows «Brief · N» (the
  tasks still open); five minutes before it a notification opens the brief.
- **The Teams transcript (.vtt)** can be added to a recording (its ⋯ menu): a version of its own, and
  its names go to the voices still called «Participant N».
- **«Locate file…»** for a recording whose file was moved, checked by its length.
- **Playlists**: a link to a playlist or a channel asks whether to download all of it (each video a
  recording in a folder of its own) or the first video.
- **The recording is safer.** The computer's sound follows the output device Windows uses (a headset
  plugged in mid-call); a call with the computer silent for a minute is said at once. A recording whose
  window was closed or reloaded is saved with its notes by itself; after a crash its parts become one
  recording with its notes. Long recordings are mixed with the same memory (~150 MB) at any length, with
  progress.
- **Files dropped on the window are added where they are**, without a copy; a file already in the
  library is not added again.
- **The queue**: a meeting just recorded is transcribed before a dub or a translation; cancelling a
  recording waiting in the queue works at once.
- **Simpler screens**: echo and voice cleanup decide by themselves (their switches in Settings →
  Recording → More); the studio's captions row keeps «Captions» and «Translation», the rest under the
  gear; the assistant without a model says so once; tasks fit a narrow window.
- **Fixes after a triple audit**:
  - the cloud model is never used without your consent;
  - recordings of a «local only» folder stay protected when the folder is deleted;
  - links in the AI's text open in the browser, not in the app's window;
  - the calendar handles time zones on Windows (Outlook's zone names, summer time of other zones),
    moved meetings of a series, «the first Monday of the month» and the 31st;
  - edits made while participants are split anew are no longer lost;
  - errors are said in plain words;
  - the Word export takes text pasted from Word;
  - sound retention counts from when the recording came into the app;
  - an update downloaded before a newer one came out is downloaded again;
  - dictation stays out of the clipboard history;
  - large libraries open faster.

## 0.8.6 — English

- **No more voices twice in recordings through speakers.** The capture of the computer's sound lost
  pieces when the app was busy (Windows said so thousands of times in a meeting) and put silence where
  sound only came late: the track drifted against the microphone. Silence now goes in only where sound
  is really missing, lost pieces are filled, and the track never runs ahead of the clock.
- **AI voice cleanup of the microphone** (DeepFilterNet 3, MIT / Apache 2.0): noise — a fan, the
  keyboard, the street — is taken out of the microphone when the recording is saved, the voice kept.
  Download the filter (27 MB) in Settings → Recording or in the studio's «Automatically».
- **Imported files stay where they are**: «Files…» opens the Windows picker and adds the files by
  their place, without a copy. A setting in Settings → Recording keeps copying them if you prefer.
- **Unloading the analysis model with the video card busy** waits longer, finds its process, and is
  retried by itself until the card is free.
- The compact view of a Teams meeting no longer counts as another meeting; a Teams window closing
  no longer breaks the captions search.

## 0.8.5 — English

- **The recording follows the Teams meeting.** Going into another meeting saves the recording and
  starts a new one named after that meeting; when the meeting is over (its window gone for 30 s) the
  recording stops. Teams keeps the microphone from one meeting to the next, so the first recording
  went on through the second. A window counts as a meeting only with the button that leaves the call
  (switching chats in the main window does not restart anything). The switch is in the studio, under
  «Automatically».
- **The participants' names in the analysis.** Overviews, chapters, templates, questions to a
  recording and the task search get the list of who was in the meeting (named speakers, studio marks,
  Teams captions, calendar invitees, as written in «All people», with their role) and write the names
  that way; a name still misspelt by a letter or two is put right, its case ending kept.

## 0.8.4 — English

- **Voices no longer come twice in a recording through speakers.** The system sound and the microphone
  could drift tens of seconds apart (a voice was heard again «from the future»); the echo was looked
  for within 2 s only and nothing was lined up. The delay is now found first by the loudness of the
  two tracks, up to 90 s apart and all along the recording, then measured exactly; the log tells how
  far apart the tracks were and how much silence the system sound capture put in.
- **«Unload all» stops the analysis too.** An overview, chapters or an answer of the assistant being
  written is shown as using the model; unloading asks, then stops it at once instead of letting the
  next part load the model again.
- **Studio captions:** who spoke is on every line, as in Teams — the name and a round mark with the
  initials in that person's colour.
- **A person's own photo** («Фото…» on a speaker card, 📷 in «All people») shows instead of the
  initials on the cards, in the directory and on the studio's captions.

## 0.8.3 — English

- **«Separate by voice» in the transcript bar**, next to the models, as well as on the participants tab.
- **The AI mark** on the buttons that run a model: Transcribe, Merge all, Separate by voice. «No fillers»
  works by a list, without a model, and lost its sparkle icon.
- **Studio captions:** scrolled up to read, the text no longer jumps to the end at every new line;
  «↓ To the new lines» brings you back.
- **Teams names in the studio** now reach every line of a long monologue (a Teams line lasts as long
  as the person speaks), and appear as soon as the Teams captions come.
- **Library:** only what is open is blue. With the studio open, the running recording is lit and the
  recording opened last keeps a soft mark; opening a recording dims the running one.
- **A click on a notification opens what it is about:** the finished recording, the studio with the
  recording running, the recording just saved, or the settings of a hotkey that does not work.

## 0.8.2 — English

- **«Separate again» on the participants tab.** The lines are separated by voice again without
  transcribing the text: say how many people spoke at most, or let the voices decide. Lines you
  corrected stay whole with your text; names come back from known voices, studio marks, Teams
  captions and the names you gave. Use it on recordings made before 0.8.1 where everyone became
  one speaker.

## 0.8.1 — English

- **Participants are told apart again.** In a call a few phrases are no one's voice (a laugh, a noise,
  a cut-off word); each became a speaker of its own, so with six participants said (from the calendar
  or Teams captions) the whole meeting went to one person, and without a count it came out as one
  speaker as well. Such phrases are now set aside while the voices are grouped and then go to the
  nearest voice.
- **The number of participants is the most there are.** The count from the calendar or captions is an
  upper bound: ten invited and two speaking stay two people.
- Voices of different people coming through the same call codec are no longer merged into one.
- Names from Teams captions now land on separate voices, one name each.

## 0.8.0 — English

A release of fixes and speed-ups after an independent audit of the whole code by three models.

- **Stop is instant.** A recording is in the library at once («Mixing the tracks») with its notes,
  marks and Teams captions; echo removal and the mix run in the background, then it queues itself.
  Closing the app during the mix is warned about; parts are never lost when the mix fails.
- **Recording is sturdier.** A failed start no longer leaves the computer's sound recording; Stop
  during the start stops it; a lost capture of the computer's sound is said at once; recording chunks
  are numbered (none twice, none out of place, a delay is said and retried for two minutes, a lost one
  no longer ends the rest); a microphone-only recording is seekable; «Save sound» and cuts never
  destroy the file they replace.
- **Teams captions:** no slowdown through long meetings, lines on screen before the recording do not
  name voices, a short «Yes» no longer overwrites an earlier line, captions switched on mid-meeting
  count, one reader at a time; the captions search backs off while captions are off.
- **Precise mode** keeps your corrections in the main model's text, reuses other models' versions only
  when made the same way, keeps the language, survives a cancel and a restart.
- **Models and memory:** a transcription no longer unloads the live captions' model; a Whisper that
  fell back to the processor is known as such; the analysis model stays as long as the settings say
  (unloaded at once only for a transcription); a forced unload stops only that model's process; echo
  removal needs ~2 GB less; the dictionary is 5× faster; status, player and model polls no longer read
  whole transcripts; the parts of a long recording are read once for the overview and chapters.
- **Editing:** typed text survives a redraw; a click on another recording is not lost; the word
  playing is highlighted correctly with «No fillers»; edits wait during a merge of versions; names
  given on screen stay after «Merge versions».
- **Security:** text from the analysis model can no longer call page functions.
- Also: «Show in folder» with network paths refused; ticked tasks stay done; a cancelled first
  transcription keeps its searchable part; meaning search indexes edits made while indexing; the
  watched folder skips the library's own recordings; work files of cancelled jobs are cleaned up.

## 0.7.10 — English

- **Recordings through speakers no longer sound like two people at once:** the system sound is put in
  the mix where the microphone heard it (measured in the sound, not by when the tracks said they
  began), and the speakers' echo is followed through the whole recording, jumps included.
- **«Show in folder» selects the file** instead of opening Documents (a space in the path confused
  Explorer).

## 0.7.9 — English

- **Studio: live caption lines say who said them** — from the Teams captions (their words and time fit
  the line) or the last «Speaking now» clicked; the name stands over a line when the speaker changes.
- **Teams captions keep finished phrases:** Teams rewrites a line while it is said; each phrase is now
  kept once, in its final wording, instead of every intermediate reading.
- «Check» in Settings → Recording shows the last lines read while a recording is on.
- Library: the bar of several selected recordings goes away with the selection (a click on one record,
  ✕ or Esc).

## 0.7.8 — English

- **Teams captions are read again:** the Windows component that reads windows (UI Automation) failed to
  load («Could not load file or assembly 'UIAutomationClient'»); it now loads by its full name or its
  file. «Check» in Settings → Recording shows whether the captions are seen.

## 0.7.7 — English

- **«All models» in the recognition row:** picked, the models it will run light up and the status says
  their order; «Transcribe precisely» then runs them and merges the versions. A model that already
  transcribed the recording is not run again: its version is used as it is.
- **The status says which model works now** (not «Auto: by language»), each model of the precise mode
  in turn.
- **Teams captions are found more reliably:** the panel with the lines, not the «Caption settings»
  button, also in a large meeting window. «Check» in Settings → Recording shows what the app sees in
  Teams right now, without a recording.
- **«Never for this meeting and its repeats»** in the question before a calendar meeting; taken back on
  the home page.

## 0.7.6 — English

- **Who speaks, from the meeting.** The studio has a «Participants» block: how many people are at the
  meeting (the calendar's guests are offered) and «Speaking now» marks — a click on a name while that
  person talks names their voice after transcription.
- **Microsoft Teams captions (optional, Settings → Recording, off by default).** While recording, the
  names above the Teams live captions are read the way Windows Narrator reads a window (nothing is
  pressed or sent anywhere): the participants appear in the studio by themselves, voices get real names,
  and the captions are kept as a transcript version of their own («Teams captions» chip). How to turn
  the captions on in Teams — in the app and in docs/teams-captions.md.
- **The recognition row shows the models as chips** with the state of each one's text (ready, none,
  running, not downloaded) and «Merge all»; with the merged text shown, the chips of the models it was
  made from light up. Whisper Pro is always among the precise mode's models; the first-run wizard can
  switch the precise mode on, marked as recommended for the best quality.
- **Memory:** before the analysis model answers, idle speech models (the captions' worker too) are
  unloaded, and the analysis model leaves memory 20 s after its last answer.
- **Speakers:** a count of one or two said for a recording is corrected when the voices clearly make
  three or more.
- **Live captions** no longer jump after the window comes back from being minimized.
- **A stopped recording stays in the library** marked as being saved while its tracks are mixed (minutes
  for a long meeting), instead of disappearing until it is ready.

## 0.7.5 — English

- **One model in memory at a time.** The precise mode runs the speech models one after another, each
  unloaded before the next; the speech models go before the analysis model works and the analysis models
  before a speech model loads. Ollama keeps one model at a time (live captions with translation aside).
- **The precise mode is picked in the «Recognition» row** of a recording: «Precise: all models + merging»
  next to the models. The row is always in sight in its frame instead of folding into a small mark.
- **A disputed word says who picked its variant:** the analysis model by meaning, or the most accurate
  model when the analysis model did not decide it.
- **A recording started or stopped by itself (a call, a calendar meeting) shows a Windows notification**
  with what is recorded and how to stop it.
- **Speakers:** an invited person's name a speaker already has stays offered and merges the two speakers;
  typing it offers the same. Merging people in «All people» says it is working.
- **Library:** a compact list grouped by day by default; days read as dividers, today in blue.

## 0.7.4 — English

- **Precise mode: several models + merging** (Settings → Recognition, and a switch per recording in the
  import window). Every new recording is recognized by the other downloaded models too and the versions
  are merged: where the models heard different words, the analysis model picks the variant that fits the
  words around it, a portion of places at a time. Each model's version stays in the list above the text.
- **Recordings through speakers no longer sound doubled.** The system audio started before the
  microphone and lost its pauses, so voices came twice, one late; the tracks now line up. And the
  speakers' echo heard by the microphone is taken out when the recording is saved (Settings → Recording,
  on; with headphones nothing changes).
- **Cancel and «Unload» are a switch.** Cancel stops at once, even in the middle of an overview; a model
  not in use is unloaded at once, one in use after a stop you confirm.
- **Studio:** live captions keep up after the window was minimized; switching captions off and on keeps
  the lines, and «Questions» see the whole recording; the recording bar fits any width and scale.
- **Library:** a running recording has a row at the top with its time; a click opens the studio with the
  captions.
- Analysis names speakers as the transcript labels them, not «User» or a made-up name.

## 0.7.3 — English

- **The dictionary works with every speech model.** Before, only Whisper took it, as a hint; GigaAM and
  Parakeet ignored it. Now after recognition (recordings, live captions, dictation) a dictionary word
  replaces what was heard for it: its **variants** («may be recognized as»: `клод, klot` for Claude) and,
  with the new switch on, words that **sound like it** in Latin or Cyrillic («klot», «клода» → «Claude»,
  «в кубернетисе» → «в Kubernetes»). Live captions on Whisper get the dictionary as a hint too.
- **The overview of a long meeting covers it from the beginning.** The notes of all parts of an
  hour-and-a-half recording ran over the model's context and the beginning was silently dropped; they are
  now condensed until they fit. The topics above the timeline are fixed the same way, and the highlights
  and «Since last time» no longer read only the first part of a long meeting.
- **Tasks:** far fewer of them from a long meeting: each one is checked a second time against what was
  said, repeats are merged, and a long meeting is read part by part to its end. A renamed speaker's tasks
  take the new name.
- **Topics above the timeline** are made by themselves with the overview of a meeting of 10 minutes or more.
- **«It's me»** on a second speaker of a recording offers to merge it into your card; a speaker with a
  default name takes your name.
- **An analysis model no longer thinks for many minutes:** an answer stops at 3072 tokens, and the overview
  of a long recording says which part it reads.
- **A video card PyTorch has no kernels for** («no kernel image is available»): the speaker model runs on
  the processor instead of failing.
- The open view and the open tab of a recording are blue in the top bar.

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

## 0.9.4

- **«Субтитры и текст»** в полосе встречи во время записи: студия с живыми субтитрами и текстом из любого раздела.
- **Путь в студию — в кнопке записи**: во время записи нажатие на точку, время или источники открывает студию; «Студия ›»
  между ними и «Стоп» показывает, включены ли субтитры (зелёная рамка, пока они выключены). При первой записи под ней
  появляется подсказка, где субтитры и текст; закрытая, она больше не показывается.
- **Звонок — тоже встреча**: пока микрофон держит приложение звонка (Teams, Zoom, Telegram…) или браузер, расшифровки
  ждут, даже без записи и без встречи в календаре. Во время встречи расшифровка начинается только по «Расшифровать»
  и «Да, начать сейчас».
- **Голосовая заметка — не встреча**: запись, сделанная вручную без звонка и без встречи в календаре, больше не
  задерживает расшифровки ни во время записи, ни 2 минуты после неё. Задерживает только запись встречи (начатая
  звонком или календарём либо следующая за встречей Teams); пауза в 2 минуты — только после встречи.
- **Очередь говорит, чего ждёт**: «Идёт встреча» или «Пауза после встречи · 1:40» с обратным отсчётом — в окне
  очереди, на островке полосы, в самой полосе и в строке состояния. У каждой расшифровки, ждущей конца встречи, есть
  «Начать сейчас» (после того же вопроса, что и у «Расшифровать» во время встречи).
- **Субтитры с Teams больше не дёргаются**: строка сохраняет найденного говорящего, а место под имена не пропадает.
- **Одна строка над текстом студии**: слева вкладки «Текст · Мои заметки · Вопросы», справа «Субтитры» с переключателем,
  язык перевода (меню), память моделей субтитров (окно с моделями распознавания и перевода, их размером и состоянием)
  и шестерёнка с остальными настройками.
- **Перенесённая или отменённая в календаре встреча не напоминает о себе в прежнее время**: календарь читается заново
  за две минуты до каждого напоминания и начала каждой встречи, и напоминание следует этому чтению (о перенесённой
  встрече напомнит её новое время). Если чтение не удалось, напоминание приходит как раньше. Пока до встречи меньше
  часа, календарь читается каждые 5 минут вместо 15.
- **Модель перевода для живых субтитров**: модели субтитров предлагают одну модель Tencent Hy-MT3 (Apache 2.0) по
  видеокарте — Hy-MT3 7B (4,9 ГБ) на картах от 10 ГБ, иначе Hy-MT3 1.8B (1,3 ГБ); в замерах программы обе переводят
  с английского на русский и обратно точнее прежних моделей Gemma. Скачивается только по «Скачать» (в окне моделей
  субтитров или в «Настройки → ИИ-анализ»); тогда «Качество» переводит моделью Hy-MT3 7B (иначе 1.8B), а «Быстро» —
  Hy-MT3 1.8B (иначе Gemma 4 E2B). Без неё всё работает как прежде. Модель 1.8B настраивается в Ollama с рабочим
  шаблоном чата (шаблон из её файла не передаёт модели текст).
- **Свой блок для моделей перевода** в «Настройки → ИИ-анализ» — «Модели перевода (Ollama)», под моделями анализа:
  обе модели Hy-MT3 (подходящая этому компьютеру отмечена «Рекомендуется для этого компьютера», другую тоже можно
  скачать), с измеренным временем перевода фразы и видеопамятью вместе с распознаванием. Два списка выбирают модель
  «Качества» и «Быстро» для субтитров: «Авто · <модель, которую оно берёт сейчас>», установленные модели перевода и
  модели анализа; выбранная модель, если её удалить, уступает место «Авто», а модель, выбранная в студии, по-прежнему
  действует до конца сеанса субтитров. Диктовку с переводом теперь переводит модель «Качества» (Hy-MT3, если
  установлена, — промптом со своей карточки), иначе модель анализа, как раньше.
- **Модели перевода больше не в списке моделей анализа**: Hy-MT3 и TranslateGemma, установленная в Ollama вручную,
  не пишут анализ и показываются только среди моделей перевода. TranslateGemma (Gemma Terms of Use) программа не
  предлагает скачать; установленная, она отмечена «Локальная · Gemma Terms ⚠» и «Проверьте лицензию перед
  коммерческим использованием» и переводит промптом со своей карточки.
- **Настройки проще, ничего не спрятано**: нет «Дополнительно»; каждая настройка — строка с коротким названием,
  пояснением только там, где последствие неочевидно, и переключателем у правого края, во всех разделах. Переключатель
  с режимом рядом — один список, где «Выключено» — один из вариантов (режим «Только запись», уведомления о встречах,
  GigaAM и Parakeet на видеокарте). Поиск находит настройки и по прежним названиям.
- **Модели выгружаются через минуту после обработки**: когда в очереди ничего не выполняется и не ждёт (расшифровка
  с автоматическим анализом — одна задача) и программой не пользуются 60 секунд, модели распознавания и модель
  анализа выгружаются; модель, к которой обращались вручную (вопрос ассистенту), остаётся на время из «Выгружать
  модели через». Запуск субтитров выгружает модель анализа, которую они не используют (кроме времени идущего
  анализа), переключение «Качество» ↔ «Быстро» выгружает предыдущую модель перевода, а модели субтитров выгружаются
  через минуту после их окончания. Каждая выгрузка записывается в журнал с причиной.
- **Выбор в студии сохраняется**: включённые или выключенные «Субтитры», язык перевода, «Качество / Скорость», модель
  субтитров и модель перевода хранятся в настройках и остаются после новой записи, перезапуска и запуска на другом
  порту. «Субтитры» — это «Включать субтитры при начале записи», модель субтитров — «Модель субтитров», модель
  перевода — модель выбранного режима в «Моделях перевода»: в настройках те же значения. Модели можно выбрать и до
  записи. Шаблон записи больше не переключает субтитры и перевод. При «Не мешать на встречах» субтитры не включаются
  сами только на встречах; голосовая заметка начинается с ними.

## 0.9.3

- **Неверное имя человека исправляется одним нажатием**: в анализе записи имя участника — неброская кнопка;
  её меню переименовывает участника («Переименовать участника…») или ставит на его место другого человека
  («Это другой человек…», из контактов или введённое имя), и анализ сразу показывает новое имя. В брифе,
  дайджесте и других ответах ассистента имена участников цитируемых записей — такие же кнопки: меню
  перечисляет эти записи, и другой человек заменяет участника в них и имя в тексте ответа.
- **«Свести сейчас»**: остановленная запись, чьё сведение ждёт встречи, называет её (встреча из календаря и её конец)
  и сводится сразу по кнопке.
- **Встреча, из которой вышли раньше, больше не держит сведение**: после остановки записи, если микрофон не занят
  приложением звонка, встреча из календаря считается законченной.
- **Бриф, дайджест и обзоры ссылаются на встречи целиком**: их метки показывают дату встречи и открывают её, а не
  «▶ 00:00».
- **«Открытых задач с прошлой встречи»** в полосе встречи открывает бриф с ними.
- **Проверка обновлений**: когда GitHub ограничивает API (403, 60 запросов в час на адрес), релиз находится по
  открытой ленте и его собственным файлам; подпись проверяется как всегда.

### А также в 0.9.2

- **Полоса встречи сверху держит текст на месте**: ничего больше не уходит под её кнопки; островок очереди называет
  причину ожидания коротко («Ждут конца встречи»), полная фраза — в подсказке.
- **«записано N мин»** видно целиком; длинное название записи плавно гаснет к концу и прокручивается до конца при
  наведении на полосу.

### А также в 0.9.1

- **Короткая запись сводится сразу.** Запись до 3 минут больше не ждёт две минуты после окончания, пока сведутся
  её дорожки: сведение занимает секунды. Длинная запись по-прежнему ждёт конца встречи («Не мешать на встречах»).
- **Ожидание объяснено.** Пока сведение ждёт, запись показывает причину и отсчёт — «Начнётся через 1:40 — пауза на
  случай, если следующая встреча начнётся сразу» или «Начнётся после встречи», пока идёт звонок или встреча по
  календарю, — а не 1 % «после встречи».
- **Запись можно удалить, пока её дорожки ждут сведения или сводятся.** Ожидающая удаляется сразу вместе с
  дорожками; сводящаяся — как только сведение закончится («Запись удалится, как только сведутся дорожки»). Дорожки
  не остаются на диске, в том числе после перезапуска в это время.
- **Удаление нескольких записей** называет причину, по которой часть из них не удалилась, а не «возможно, они
  сейчас обрабатываются».
- **Красная кнопка во время записи**: останавливает только «Стоп»; точка, время и источники открывают студию записи.
- **Панель выделения в «Записях»**: спокойные действия со значками, ✕ с числом выбранных, «Удалить» отдельно и красным.

### А также в 0.9.0

- **«Назад» и «Вперёд»** в начале верхней полосы, как в браузере (а также Alt+← / Alt+→ и боковые кнопки мыши).
- **Время записи** на красной кнопке открывает студию записи; субтитры одного размера во всех окнах.
- **Фичи в отдельной панели**: «Управлять фичами…» в меню фич «Обзора» и «Записей» и в чипе фичи записи открывает
  панель поверх любого раздела; в «Словаре» карточка фич остаётся.
- **Ассистент**: на приветствие отвечает коротко; общий вопрос (объяснить понятие, дать совет, написать текст)
  получает ответ модели из её знаний, с размышлениями и пометкой, что он не по записям; по записям отвечает
  только на вопросы о них, а в источниках — только места, на которые ссылается ответ. Ассистент помнит три
  последних вопроса разговора, так что «а подробнее?» работает.
- **Имена участников в анализе следуют переименованиям** и после повторного разделения или объединения
  участников: анализ ссылается на участника, а не на имя, записанное в тот момент.
- **Уведомления Windows, меню значка в трее и напоминания о встречах** — на языке интерфейса.
- Акцент «Вишня» стал «Малиной» и больше не сливается с красным цветом записи. Меню и окна не выходят за
  пределы окна программы. Поля «Словаря» поясняют себя.

- **Новый вид — «Пульт встреч»**: слева полоса разделов (Сегодня, Обзор, Записи, Задачи, Люди, Словарь, Ассистент;
  Ctrl+1…6), внизу «Настройки» и «Выйти». Старой боковой панели больше нет.
- **Полоса встречи сверху** показывает, что происходит: свободно до конца дня, встреча через N минут, идёт без
  записи, идёт запись, ждёт расшифровки, итоги готовы — и кнопку этого момента (Подключиться, Записать,
  Отметить момент, Открыть итоги), рядом «＋ Импорт».
- **Нагрузка в строке состояния**: процессор, память и видеопамять с долей самой программы; по щелчку — модели
  в памяти, у каждой своя «Выгрузить».
- **«Сегодня» и «Обзор»**: «Сегодня» — календарь (день, неделя, месяц; прошедшее рабочее время подсвечено) и
  карточки дня; «Обзор» — аналитика: плитки «Статистики» с динамикой и выбором показателей, диаграммы
  столбцами, полосами, кругом или линией, у каждой части свой цвет.
- **«Мои программы»** (по умолчанию выключено): как рабочее время делится между программами. Хранится
  только название программы — без заголовков окон, нажатий клавиш и снимков экрана, данные не покидают компьютер.
- **«Записи»**: таблица, карточки и папки; «Колонки» во всех видах, компактные строки; поиск показывает найденные
  места в тексте; панель выделения; импорт из меню, по Ctrl+O или перетаскиванием файлов на любом экране.
- **Запись**: сначала «Расшифровка» — чатом или текстом; «Анализ» карточками со ссылками ▶ на моменты;
  «Сведения» с «Расшифровать заново» и «Пересоздать анализ»; проигрыватель ниже, сворачивается в одну строку.
- **«Задачи»** — таблицей, карточками или календарём; **«Люди»** и **«Словарь»** — отдельные разделы; ассистент
  показывает источники метками ▶ времени; после обновления — одно окно вместо двух.
- Исправления: выход из программы или выключение Windows во время расшифровки больше не считаются сбоем; запуск
  во время обновления больше не откатывает установку; MCP-сервер сразу учитывает настройку диктовок; резервная
  копия и восстановление сохраняют отработанное время этого компьютера.
- **«Не мешать на встречах» держит всё**: пока идёт встреча и две минуты после неё, ждут расшифровка, сведение
  остановленной записи и модели участников; Nemotron выгружается вместе с остальными моделями речи. Модели
  больше не загружаются посреди звонка и не тормозят компьютер.
- **Субтитры по умолчанию выключены** и не включаются сами, пока действует «Не мешать на встречах»; включить
  можно на экране записи или в «Настройки → Запись».
- **Часы встреч в «Обзоре»** снова считают все записи, в том числе ещё не расшифрованные и отменённые.
- **Перетаскивание виджетов** в «Настроить»: виджет приподнимается, а место показывает, куда он встанет.
- **Календарь, месяц**: сегодняшний день снова выделен.
- В «Настроить» у каждого виджета своё название вместо служебного ключа.
- Настройки: вкладки переключаются с плавным появлением, как разделы.
- Тексты интерфейса — проще и в спокойном, деловом тоне.
- **Анализ только на компьютере**: возможность отправлять текст в облачные модели по API убрана. Сохранённые
  API-ключи, журнал облачных запросов и пометки «только локально» удаляются; анализ всегда выполняет Ollama.
  Записи, помеченные раньше «только локально», по-прежнему скрыты от агента (MCP).
- **Один вид у всех окон, меню и уведомлений**: заголовок со значком, кнопка закрытия на одном месте, одна
  кнопка везде (32 px, одинаковые углы), боковые панели «Обзора» выезжают и уезжают; уведомления показывают
  свой вид цветным квадратом и оставшееся время тонкой полоской.
- **«Словарь»**: слова — главная карточка с группами и строками как в «Записях»; предложения, исправление и
  фичи — в колонке справа начиная с 1100 px.
- **Щелчок по дню недели или месяца открывает этот день**: его встречи, записи этого дня и отработанные часы;
  ‹ › — на день назад и вперёд.
- **Ассистент**: понятная кнопка отправки; по заголовку разговора видно, что его можно переименовать.
- Исправления: календарь из классического Outlook без почтового профиля больше не открывает мастер первого
  запуска Outlook каждые 15 минут; удаление модели Ollama при необходимости запускает Ollama и удаляет модель
  под её настоящим именем; ярлыки показывают новый значок после следующего обновления; в «О программе» — новый значок.
- **Акцент на выбор** в «Настройки → Общие»: восемь цветов для выделенных кнопок и отметок; фон остаётся один.
- Настройки на широком окне — в две колонки; «Сбросить вкладку» убрана. Сегодняшний день в «Сегодня» — в зелёной
  рамке. Кнопки у моделей одного размера; строки для агента копируются значком в самом коде.
- **«Выйти»** внизу полосы разделов — как кнопка питания Windows: «Свернуть в трей» или «Выйти полностью»
  (Ctrl+Q), полный выход всегда с подтверждением.
- **Очередь — островок в полосе сверху**: пока ничего не выполняется, его нет; идёт задача — её кольцо прогресса и
  «+N в очереди»; щелчок открывает очередь. Кнопки «Очередь» на полосе разделов больше нет.
- **Один, приглушённый акцент** у кнопок, переключателей и выбранного пункта во всех переключателях; в меню текущий
  пункт выделен акцентом вместо галочки. Повторный щелчок по кнопке меню закрывает его; Esc закрывает только верхнее
  окно; открыто одно меню за раз.
- **«＋ Импорт ▾»** как «● Запись ▾»: кнопка открывает всё сразу, меню — окно для файлов, папки или ссылки.
- **Расшифровка**: у записи без текста — одна карточка с выбором модели и ходом сведения или распознавания; модель,
  участники и инструменты текста — в одну строку.
- **«Мои программы»** считают только минуты с действиями (геймпад тоже); время встреч — по записям.
- Исправления: вопрос ассистенту сразу после запуска дожидается, пока Ollama запустится; календарь из Outlook больше
  не закрывает Outlook, с которым работают; «Свернуть в трей» — только когда
  есть значок в трее; обновление, прерванное отключением питания, больше не мешает запуску; полоса сверху не
  запрашивает календарь по кругу после ошибки; запись, открытая и тут же покинутая, больше не остаётся скрытой;
  виджеты перетаскиваются верно при любом масштабе; записи, закрытые раньше от агента, остаются закрытыми и после
  удаления их папки; окно горячих клавиш показывает Ctrl+1…6.

## 0.9.2

- **Полоса встречи сверху держит текст на месте**: ничего больше не уходит под её кнопки; островок очереди называет
  причину ожидания коротко («Ждут конца встречи»), полная фраза — в подсказке.
- **«записано N мин»** видно целиком; длинное название записи плавно гаснет к концу и прокручивается до конца при
  наведении на полосу.

### А также в 0.9.1

- **Короткая запись сводится сразу.** Запись до 3 минут больше не ждёт две минуты после окончания, пока сведутся
  её дорожки: сведение занимает секунды. Длинная запись по-прежнему ждёт конца встречи («Не мешать на встречах»).
- **Ожидание объяснено.** Пока сведение ждёт, запись показывает причину и отсчёт — «Начнётся через 1:40 — пауза на
  случай, если следующая встреча начнётся сразу» или «Начнётся после встречи», пока идёт звонок или встреча по
  календарю, — а не 1 % «после встречи».
- **Запись можно удалить, пока её дорожки ждут сведения или сводятся.** Ожидающая удаляется сразу вместе с
  дорожками; сводящаяся — как только сведение закончится («Запись удалится, как только сведутся дорожки»). Дорожки
  не остаются на диске, в том числе после перезапуска в это время.
- **Удаление нескольких записей** называет причину, по которой часть из них не удалилась, а не «возможно, они
  сейчас обрабатываются».
- **Красная кнопка во время записи**: останавливает только «Стоп»; точка, время и источники открывают студию записи.
- **Панель выделения в «Записях»**: спокойные действия со значками, ✕ с числом выбранных, «Удалить» отдельно и красным.

### А также в 0.9.0

- **«Назад» и «Вперёд»** в начале верхней полосы, как в браузере (а также Alt+← / Alt+→ и боковые кнопки мыши).
- **Время записи** на красной кнопке открывает студию записи; субтитры одного размера во всех окнах.
- **Фичи в отдельной панели**: «Управлять фичами…» в меню фич «Обзора» и «Записей» и в чипе фичи записи открывает
  панель поверх любого раздела; в «Словаре» карточка фич остаётся.
- **Ассистент**: на приветствие отвечает коротко; общий вопрос (объяснить понятие, дать совет, написать текст)
  получает ответ модели из её знаний, с размышлениями и пометкой, что он не по записям; по записям отвечает
  только на вопросы о них, а в источниках — только места, на которые ссылается ответ. Ассистент помнит три
  последних вопроса разговора, так что «а подробнее?» работает.
- **Имена участников в анализе следуют переименованиям** и после повторного разделения или объединения
  участников: анализ ссылается на участника, а не на имя, записанное в тот момент.
- **Уведомления Windows, меню значка в трее и напоминания о встречах** — на языке интерфейса.
- Акцент «Вишня» стал «Малиной» и больше не сливается с красным цветом записи. Меню и окна не выходят за
  пределы окна программы. Поля «Словаря» поясняют себя.

- **Новый вид — «Пульт встреч»**: слева полоса разделов (Сегодня, Обзор, Записи, Задачи, Люди, Словарь, Ассистент;
  Ctrl+1…6), внизу «Настройки» и «Выйти». Старой боковой панели больше нет.
- **Полоса встречи сверху** показывает, что происходит: свободно до конца дня, встреча через N минут, идёт без
  записи, идёт запись, ждёт расшифровки, итоги готовы — и кнопку этого момента (Подключиться, Записать,
  Отметить момент, Открыть итоги), рядом «＋ Импорт».
- **Нагрузка в строке состояния**: процессор, память и видеопамять с долей самой программы; по щелчку — модели
  в памяти, у каждой своя «Выгрузить».
- **«Сегодня» и «Обзор»**: «Сегодня» — календарь (день, неделя, месяц; прошедшее рабочее время подсвечено) и
  карточки дня; «Обзор» — аналитика: плитки «Статистики» с динамикой и выбором показателей, диаграммы
  столбцами, полосами, кругом или линией, у каждой части свой цвет.
- **«Мои программы»** (по умолчанию выключено): как рабочее время делится между программами. Хранится
  только название программы — без заголовков окон, нажатий клавиш и снимков экрана, данные не покидают компьютер.
- **«Записи»**: таблица, карточки и папки; «Колонки» во всех видах, компактные строки; поиск показывает найденные
  места в тексте; панель выделения; импорт из меню, по Ctrl+O или перетаскиванием файлов на любом экране.
- **Запись**: сначала «Расшифровка» — чатом или текстом; «Анализ» карточками со ссылками ▶ на моменты;
  «Сведения» с «Расшифровать заново» и «Пересоздать анализ»; проигрыватель ниже, сворачивается в одну строку.
- **«Задачи»** — таблицей, карточками или календарём; **«Люди»** и **«Словарь»** — отдельные разделы; ассистент
  показывает источники метками ▶ времени; после обновления — одно окно вместо двух.
- Исправления: выход из программы или выключение Windows во время расшифровки больше не считаются сбоем; запуск
  во время обновления больше не откатывает установку; MCP-сервер сразу учитывает настройку диктовок; резервная
  копия и восстановление сохраняют отработанное время этого компьютера.
- **«Не мешать на встречах» держит всё**: пока идёт встреча и две минуты после неё, ждут расшифровка, сведение
  остановленной записи и модели участников; Nemotron выгружается вместе с остальными моделями речи. Модели
  больше не загружаются посреди звонка и не тормозят компьютер.
- **Субтитры по умолчанию выключены** и не включаются сами, пока действует «Не мешать на встречах»; включить
  можно на экране записи или в «Настройки → Запись».
- **Часы встреч в «Обзоре»** снова считают все записи, в том числе ещё не расшифрованные и отменённые.
- **Перетаскивание виджетов** в «Настроить»: виджет приподнимается, а место показывает, куда он встанет.
- **Календарь, месяц**: сегодняшний день снова выделен.
- В «Настроить» у каждого виджета своё название вместо служебного ключа.
- Настройки: вкладки переключаются с плавным появлением, как разделы.
- Тексты интерфейса — проще и в спокойном, деловом тоне.
- **Анализ только на компьютере**: возможность отправлять текст в облачные модели по API убрана. Сохранённые
  API-ключи, журнал облачных запросов и пометки «только локально» удаляются; анализ всегда выполняет Ollama.
  Записи, помеченные раньше «только локально», по-прежнему скрыты от агента (MCP).
- **Один вид у всех окон, меню и уведомлений**: заголовок со значком, кнопка закрытия на одном месте, одна
  кнопка везде (32 px, одинаковые углы), боковые панели «Обзора» выезжают и уезжают; уведомления показывают
  свой вид цветным квадратом и оставшееся время тонкой полоской.
- **«Словарь»**: слова — главная карточка с группами и строками как в «Записях»; предложения, исправление и
  фичи — в колонке справа начиная с 1100 px.
- **Щелчок по дню недели или месяца открывает этот день**: его встречи, записи этого дня и отработанные часы;
  ‹ › — на день назад и вперёд.
- **Ассистент**: понятная кнопка отправки; по заголовку разговора видно, что его можно переименовать.
- Исправления: календарь из классического Outlook без почтового профиля больше не открывает мастер первого
  запуска Outlook каждые 15 минут; удаление модели Ollama при необходимости запускает Ollama и удаляет модель
  под её настоящим именем; ярлыки показывают новый значок после следующего обновления; в «О программе» — новый значок.
- **Акцент на выбор** в «Настройки → Общие»: восемь цветов для выделенных кнопок и отметок; фон остаётся один.
- Настройки на широком окне — в две колонки; «Сбросить вкладку» убрана. Сегодняшний день в «Сегодня» — в зелёной
  рамке. Кнопки у моделей одного размера; строки для агента копируются значком в самом коде.
- **«Выйти»** внизу полосы разделов — как кнопка питания Windows: «Свернуть в трей» или «Выйти полностью»
  (Ctrl+Q), полный выход всегда с подтверждением.
- **Очередь — островок в полосе сверху**: пока ничего не выполняется, его нет; идёт задача — её кольцо прогресса и
  «+N в очереди»; щелчок открывает очередь. Кнопки «Очередь» на полосе разделов больше нет.
- **Один, приглушённый акцент** у кнопок, переключателей и выбранного пункта во всех переключателях; в меню текущий
  пункт выделен акцентом вместо галочки. Повторный щелчок по кнопке меню закрывает его; Esc закрывает только верхнее
  окно; открыто одно меню за раз.
- **«＋ Импорт ▾»** как «● Запись ▾»: кнопка открывает всё сразу, меню — окно для файлов, папки или ссылки.
- **Расшифровка**: у записи без текста — одна карточка с выбором модели и ходом сведения или распознавания; модель,
  участники и инструменты текста — в одну строку.
- **«Мои программы»** считают только минуты с действиями (геймпад тоже); время встреч — по записям.
- Исправления: вопрос ассистенту сразу после запуска дожидается, пока Ollama запустится; календарь из Outlook больше
  не закрывает Outlook, с которым работают; «Свернуть в трей» — только когда
  есть значок в трее; обновление, прерванное отключением питания, больше не мешает запуску; полоса сверху не
  запрашивает календарь по кругу после ошибки; запись, открытая и тут же покинутая, больше не остаётся скрытой;
  виджеты перетаскиваются верно при любом масштабе; записи, закрытые раньше от агента, остаются закрытыми и после
  удаления их папки; окно горячих клавиш показывает Ctrl+1…6.

## 0.9.1

- **Короткая запись сводится сразу.** Запись до 3 минут больше не ждёт две минуты после окончания, пока сведутся
  её дорожки: сведение занимает секунды. Длинная запись по-прежнему ждёт конца встречи («Не мешать на встречах»).
- **Ожидание объяснено.** Пока сведение ждёт, запись показывает причину и отсчёт — «Начнётся через 1:40 — пауза на
  случай, если следующая встреча начнётся сразу» или «Начнётся после встречи», пока идёт звонок или встреча по
  календарю, — а не 1 % «после встречи».
- **Запись можно удалить, пока её дорожки ждут сведения или сводятся.** Ожидающая удаляется сразу вместе с
  дорожками; сводящаяся — как только сведение закончится («Запись удалится, как только сведутся дорожки»). Дорожки
  не остаются на диске, в том числе после перезапуска в это время.
- **Удаление нескольких записей** называет причину, по которой часть из них не удалилась, а не «возможно, они
  сейчас обрабатываются».
- **Красная кнопка во время записи**: останавливает только «Стоп»; точка, время и источники открывают студию записи.
- **Панель выделения в «Записях»**: спокойные действия со значками, ✕ с числом выбранных, «Удалить» отдельно и красным.

### А также в 0.9.0

- **«Назад» и «Вперёд»** в начале верхней полосы, как в браузере (а также Alt+← / Alt+→ и боковые кнопки мыши).
- **Время записи** на красной кнопке открывает студию записи; субтитры одного размера во всех окнах.
- **Фичи в отдельной панели**: «Управлять фичами…» в меню фич «Обзора» и «Записей» и в чипе фичи записи открывает
  панель поверх любого раздела; в «Словаре» карточка фич остаётся.
- **Ассистент**: на приветствие отвечает коротко; общий вопрос (объяснить понятие, дать совет, написать текст)
  получает ответ модели из её знаний, с размышлениями и пометкой, что он не по записям; по записям отвечает
  только на вопросы о них, а в источниках — только места, на которые ссылается ответ. Ассистент помнит три
  последних вопроса разговора, так что «а подробнее?» работает.
- **Имена участников в анализе следуют переименованиям** и после повторного разделения или объединения
  участников: анализ ссылается на участника, а не на имя, записанное в тот момент.
- **Уведомления Windows, меню значка в трее и напоминания о встречах** — на языке интерфейса.
- Акцент «Вишня» стал «Малиной» и больше не сливается с красным цветом записи. Меню и окна не выходят за
  пределы окна программы. Поля «Словаря» поясняют себя.

- **Новый вид — «Пульт встреч»**: слева полоса разделов (Сегодня, Обзор, Записи, Задачи, Люди, Словарь, Ассистент;
  Ctrl+1…6), внизу «Настройки» и «Выйти». Старой боковой панели больше нет.
- **Полоса встречи сверху** показывает, что происходит: свободно до конца дня, встреча через N минут, идёт без
  записи, идёт запись, ждёт расшифровки, итоги готовы — и кнопку этого момента (Подключиться, Записать,
  Отметить момент, Открыть итоги), рядом «＋ Импорт».
- **Нагрузка в строке состояния**: процессор, память и видеопамять с долей самой программы; по щелчку — модели
  в памяти, у каждой своя «Выгрузить».
- **«Сегодня» и «Обзор»**: «Сегодня» — календарь (день, неделя, месяц; прошедшее рабочее время подсвечено) и
  карточки дня; «Обзор» — аналитика: плитки «Статистики» с динамикой и выбором показателей, диаграммы
  столбцами, полосами, кругом или линией, у каждой части свой цвет.
- **«Мои программы»** (по умолчанию выключено): как рабочее время делится между программами. Хранится
  только название программы — без заголовков окон, нажатий клавиш и снимков экрана, данные не покидают компьютер.
- **«Записи»**: таблица, карточки и папки; «Колонки» во всех видах, компактные строки; поиск показывает найденные
  места в тексте; панель выделения; импорт из меню, по Ctrl+O или перетаскиванием файлов на любом экране.
- **Запись**: сначала «Расшифровка» — чатом или текстом; «Анализ» карточками со ссылками ▶ на моменты;
  «Сведения» с «Расшифровать заново» и «Пересоздать анализ»; проигрыватель ниже, сворачивается в одну строку.
- **«Задачи»** — таблицей, карточками или календарём; **«Люди»** и **«Словарь»** — отдельные разделы; ассистент
  показывает источники метками ▶ времени; после обновления — одно окно вместо двух.
- Исправления: выход из программы или выключение Windows во время расшифровки больше не считаются сбоем; запуск
  во время обновления больше не откатывает установку; MCP-сервер сразу учитывает настройку диктовок; резервная
  копия и восстановление сохраняют отработанное время этого компьютера.
- **«Не мешать на встречах» держит всё**: пока идёт встреча и две минуты после неё, ждут расшифровка, сведение
  остановленной записи и модели участников; Nemotron выгружается вместе с остальными моделями речи. Модели
  больше не загружаются посреди звонка и не тормозят компьютер.
- **Субтитры по умолчанию выключены** и не включаются сами, пока действует «Не мешать на встречах»; включить
  можно на экране записи или в «Настройки → Запись».
- **Часы встреч в «Обзоре»** снова считают все записи, в том числе ещё не расшифрованные и отменённые.
- **Перетаскивание виджетов** в «Настроить»: виджет приподнимается, а место показывает, куда он встанет.
- **Календарь, месяц**: сегодняшний день снова выделен.
- В «Настроить» у каждого виджета своё название вместо служебного ключа.
- Настройки: вкладки переключаются с плавным появлением, как разделы.
- Тексты интерфейса — проще и в спокойном, деловом тоне.
- **Анализ только на компьютере**: возможность отправлять текст в облачные модели по API убрана. Сохранённые
  API-ключи, журнал облачных запросов и пометки «только локально» удаляются; анализ всегда выполняет Ollama.
  Записи, помеченные раньше «только локально», по-прежнему скрыты от агента (MCP).
- **Один вид у всех окон, меню и уведомлений**: заголовок со значком, кнопка закрытия на одном месте, одна
  кнопка везде (32 px, одинаковые углы), боковые панели «Обзора» выезжают и уезжают; уведомления показывают
  свой вид цветным квадратом и оставшееся время тонкой полоской.
- **«Словарь»**: слова — главная карточка с группами и строками как в «Записях»; предложения, исправление и
  фичи — в колонке справа начиная с 1100 px.
- **Щелчок по дню недели или месяца открывает этот день**: его встречи, записи этого дня и отработанные часы;
  ‹ › — на день назад и вперёд.
- **Ассистент**: понятная кнопка отправки; по заголовку разговора видно, что его можно переименовать.
- Исправления: календарь из классического Outlook без почтового профиля больше не открывает мастер первого
  запуска Outlook каждые 15 минут; удаление модели Ollama при необходимости запускает Ollama и удаляет модель
  под её настоящим именем; ярлыки показывают новый значок после следующего обновления; в «О программе» — новый значок.
- **Акцент на выбор** в «Настройки → Общие»: восемь цветов для выделенных кнопок и отметок; фон остаётся один.
- Настройки на широком окне — в две колонки; «Сбросить вкладку» убрана. Сегодняшний день в «Сегодня» — в зелёной
  рамке. Кнопки у моделей одного размера; строки для агента копируются значком в самом коде.
- **«Выйти»** внизу полосы разделов — как кнопка питания Windows: «Свернуть в трей» или «Выйти полностью»
  (Ctrl+Q), полный выход всегда с подтверждением.
- **Очередь — островок в полосе сверху**: пока ничего не выполняется, его нет; идёт задача — её кольцо прогресса и
  «+N в очереди»; щелчок открывает очередь. Кнопки «Очередь» на полосе разделов больше нет.
- **Один, приглушённый акцент** у кнопок, переключателей и выбранного пункта во всех переключателях; в меню текущий
  пункт выделен акцентом вместо галочки. Повторный щелчок по кнопке меню закрывает его; Esc закрывает только верхнее
  окно; открыто одно меню за раз.
- **«＋ Импорт ▾»** как «● Запись ▾»: кнопка открывает всё сразу, меню — окно для файлов, папки или ссылки.
- **Расшифровка**: у записи без текста — одна карточка с выбором модели и ходом сведения или распознавания; модель,
  участники и инструменты текста — в одну строку.
- **«Мои программы»** считают только минуты с действиями (геймпад тоже); время встреч — по записям.
- Исправления: вопрос ассистенту сразу после запуска дожидается, пока Ollama запустится; календарь из Outlook больше
  не закрывает Outlook, с которым работают; «Свернуть в трей» — только когда
  есть значок в трее; обновление, прерванное отключением питания, больше не мешает запуску; полоса сверху не
  запрашивает календарь по кругу после ошибки; запись, открытая и тут же покинутая, больше не остаётся скрытой;
  виджеты перетаскиваются верно при любом масштабе; записи, закрытые раньше от агента, остаются закрытыми и после
  удаления их папки; окно горячих клавиш показывает Ctrl+1…6.

## 0.9.0

- **«Назад» и «Вперёд»** в начале верхней полосы, как в браузере (а также Alt+← / Alt+→ и боковые кнопки мыши).
- **Время записи** на красной кнопке открывает студию записи; субтитры одного размера во всех окнах.
- **Фичи в отдельной панели**: «Управлять фичами…» в меню фич «Обзора» и «Записей» и в чипе фичи записи открывает
  панель поверх любого раздела; в «Словаре» карточка фич остаётся.
- **Ассистент**: на приветствие отвечает коротко; общий вопрос (объяснить понятие, дать совет, написать текст)
  получает ответ модели из её знаний, с размышлениями и пометкой, что он не по записям; по записям отвечает
  только на вопросы о них, а в источниках — только места, на которые ссылается ответ. Ассистент помнит три
  последних вопроса разговора, так что «а подробнее?» работает.
- **Имена участников в анализе следуют переименованиям** и после повторного разделения или объединения
  участников: анализ ссылается на участника, а не на имя, записанное в тот момент.
- **Уведомления Windows, меню значка в трее и напоминания о встречах** — на языке интерфейса.
- Акцент «Вишня» стал «Малиной» и больше не сливается с красным цветом записи. Меню и окна не выходят за
  пределы окна программы. Поля «Словаря» поясняют себя.

- **Новый вид — «Пульт встреч»**: слева полоса разделов (Сегодня, Обзор, Записи, Задачи, Люди, Словарь, Ассистент;
  Ctrl+1…6), внизу «Настройки» и «Выйти». Старой боковой панели больше нет.
- **Полоса встречи сверху** показывает, что происходит: свободно до конца дня, встреча через N минут, идёт без
  записи, идёт запись, ждёт расшифровки, итоги готовы — и кнопку этого момента (Подключиться, Записать,
  Отметить момент, Открыть итоги), рядом «＋ Импорт».
- **Нагрузка в строке состояния**: процессор, память и видеопамять с долей самой программы; по щелчку — модели
  в памяти, у каждой своя «Выгрузить».
- **«Сегодня» и «Обзор»**: «Сегодня» — календарь (день, неделя, месяц; прошедшее рабочее время подсвечено) и
  карточки дня; «Обзор» — аналитика: плитки «Статистики» с динамикой и выбором показателей, диаграммы
  столбцами, полосами, кругом или линией, у каждой части свой цвет.
- **«Мои программы»** (по умолчанию выключено): как рабочее время делится между программами. Хранится
  только название программы — без заголовков окон, нажатий клавиш и снимков экрана, данные не покидают компьютер.
- **«Записи»**: таблица, карточки и папки; «Колонки» во всех видах, компактные строки; поиск показывает найденные
  места в тексте; панель выделения; импорт из меню, по Ctrl+O или перетаскиванием файлов на любом экране.
- **Запись**: сначала «Расшифровка» — чатом или текстом; «Анализ» карточками со ссылками ▶ на моменты;
  «Сведения» с «Расшифровать заново» и «Пересоздать анализ»; проигрыватель ниже, сворачивается в одну строку.
- **«Задачи»** — таблицей, карточками или календарём; **«Люди»** и **«Словарь»** — отдельные разделы; ассистент
  показывает источники метками ▶ времени; после обновления — одно окно вместо двух.
- Исправления: выход из программы или выключение Windows во время расшифровки больше не считаются сбоем; запуск
  во время обновления больше не откатывает установку; MCP-сервер сразу учитывает настройку диктовок; резервная
  копия и восстановление сохраняют отработанное время этого компьютера.
- **«Не мешать на встречах» держит всё**: пока идёт встреча и две минуты после неё, ждут расшифровка, сведение
  остановленной записи и модели участников; Nemotron выгружается вместе с остальными моделями речи. Модели
  больше не загружаются посреди звонка и не тормозят компьютер.
- **Субтитры по умолчанию выключены** и не включаются сами, пока действует «Не мешать на встречах»; включить
  можно на экране записи или в «Настройки → Запись».
- **Часы встреч в «Обзоре»** снова считают все записи, в том числе ещё не расшифрованные и отменённые.
- **Перетаскивание виджетов** в «Настроить»: виджет приподнимается, а место показывает, куда он встанет.
- **Календарь, месяц**: сегодняшний день снова выделен.
- В «Настроить» у каждого виджета своё название вместо служебного ключа.
- Настройки: вкладки переключаются с плавным появлением, как разделы.
- Тексты интерфейса — проще и в спокойном, деловом тоне.
- **Анализ только на компьютере**: возможность отправлять текст в облачные модели по API убрана. Сохранённые
  API-ключи, журнал облачных запросов и пометки «только локально» удаляются; анализ всегда выполняет Ollama.
  Записи, помеченные раньше «только локально», по-прежнему скрыты от агента (MCP).
- **Один вид у всех окон, меню и уведомлений**: заголовок со значком, кнопка закрытия на одном месте, одна
  кнопка везде (32 px, одинаковые углы), боковые панели «Обзора» выезжают и уезжают; уведомления показывают
  свой вид цветным квадратом и оставшееся время тонкой полоской.
- **«Словарь»**: слова — главная карточка с группами и строками как в «Записях»; предложения, исправление и
  фичи — в колонке справа начиная с 1100 px.
- **Щелчок по дню недели или месяца открывает этот день**: его встречи, записи этого дня и отработанные часы;
  ‹ › — на день назад и вперёд.
- **Ассистент**: понятная кнопка отправки; по заголовку разговора видно, что его можно переименовать.
- Исправления: календарь из классического Outlook без почтового профиля больше не открывает мастер первого
  запуска Outlook каждые 15 минут; удаление модели Ollama при необходимости запускает Ollama и удаляет модель
  под её настоящим именем; ярлыки показывают новый значок после следующего обновления; в «О программе» — новый значок.
- **Акцент на выбор** в «Настройки → Общие»: восемь цветов для выделенных кнопок и отметок; фон остаётся один.
- Настройки на широком окне — в две колонки; «Сбросить вкладку» убрана. Сегодняшний день в «Сегодня» — в зелёной
  рамке. Кнопки у моделей одного размера; строки для агента копируются значком в самом коде.
- **«Выйти»** внизу полосы разделов — как кнопка питания Windows: «Свернуть в трей» или «Выйти полностью»
  (Ctrl+Q), полный выход всегда с подтверждением.
- **Очередь — островок в полосе сверху**: пока ничего не выполняется, его нет; идёт задача — её кольцо прогресса и
  «+N в очереди»; щелчок открывает очередь. Кнопки «Очередь» на полосе разделов больше нет.
- **Один, приглушённый акцент** у кнопок, переключателей и выбранного пункта во всех переключателях; в меню текущий
  пункт выделен акцентом вместо галочки. Повторный щелчок по кнопке меню закрывает его; Esc закрывает только верхнее
  окно; открыто одно меню за раз.
- **«＋ Импорт ▾»** как «● Запись ▾»: кнопка открывает всё сразу, меню — окно для файлов, папки или ссылки.
- **Расшифровка**: у записи без текста — одна карточка с выбором модели и ходом сведения или распознавания; модель,
  участники и инструменты текста — в одну строку.
- **«Мои программы»** считают только минуты с действиями (геймпад тоже); время встреч — по записям.
- Исправления: вопрос ассистенту сразу после запуска дожидается, пока Ollama запустится; календарь из Outlook больше
  не закрывает Outlook, с которым работают; «Свернуть в трей» — только когда
  есть значок в трее; обновление, прерванное отключением питания, больше не мешает запуску; полоса сверху не
  запрашивает календарь по кругу после ошибки; запись, открытая и тут же покинутая, больше не остаётся скрытой;
  виджеты перетаскиваются верно при любом масштабе; записи, закрытые раньше от агента, остаются закрытыми и после
  удаления их папки; окно горячих клавиш показывает Ctrl+1…6.

## 0.8.25

- **Подключение к встрече из уведомления**: в начале встречи приходит уведомление Windows с кнопкой
  «Подключиться» — она открывает звонок по ссылке из приглашения (Teams в своём приложении, Zoom, Google Meet,
  Webex); уведомление не исчезает, пока не ответишь. Напоминание заранее — когда выберешь: от 30 секунд до 15
  минут или не напоминать. На «Главной» у начинающейся встречи есть «Подключиться».
- **Государственные праздники своей страны**: «Настройки → Календарь → Праздники», страна (около 250) и регион;
  спрашиваются при первом запуске и после этого обновления. Там же и прямо в календаре («⋯» у дня или правый
  клик) — **свои выходные и отпуск**. Выходные заштрихованы и не считаются рабочими днями на «Главной».
- **Сколько длился рабочий день**: время за компьютером (клавиатура и мышь, запись, звонок) — как статус в
  Teams; виджет «Рабочий день», часы каждого дня в календаре и напоминание через 8 часов (или сколько задано).
  Только на этом компьютере, можно выключить.
- **Карточка фичи** — из виджета «Фичи» на «Главной»: ближайшая встреча с «Подключиться», что изменилось за
  неделю, «Где мы» от модели анализа по кнопке, недели, люди, решения, задачи и встречи.
- **Что нового после обновления**: маленькое окно с новыми настройками и функциями, один раз.
- **Строка распознавания в одну линию**: «Версия: … ▾», «Расшифровать заново», «⋯» и когда сделан текст.
- **«Главная»** (была «Дэшборд»): одно оформление — стальной синий на холодном сланце; вкладки программы наверху
  вместе; виджеты заполняют ряды; прогресс периода в календарных или рабочих днях; карточки недели не рвут слова.
- Событие календаря можно отметить «не встреча» (одно или всю серию); длинные блоки и незаписанные встречи не
  считаются идущими.
- Obsidian: заметка следует за фичами и названием своей записи.
- Плавные переходы между вкладками и экранами.
- **Исправления после аудита кода**: запись, восстановленная после сбоя, больше не удаляется при том же
  запуске, а сбой во время сведения восстанавливает её целиком с заметками; запись датируется началом, а не
  «Стоп»; восстановление из копии заменяет повреждённую базу; сломанный ответ модели больше не стирает задачи;
  серии календаря не теряют последнюю встречу и 29 февраля; настройки не стирают вводимый текст; Esc закрывает
  журнал облака и окна шаблонов; агент (MCP) ничего не получает, если список «только локально» не прочитан.
- **Быстрее на большой библиотеке**: правка строк расшифровки, поиск, «Главная», день календаря и список людей
  занимают в разы меньше времени; список библиотеки не скачивается заново, пока ничего не изменилось и пока
  окно скрыто.
- **Ещё исправления по аудиту**: отмена одной задачи записи больше не отменяет следующую; задача, дважды
  прерванная при запуске, останавливается, а не возобновляется бесконечно; заметка Obsidian пишется целиком, а
  переименование сохраняет ваш раздел; повреждённая версия расшифровки не ломает запись; сроки задач читают дни
  недели только целыми словами; серии календаря в UTC сохраняют время; восстановление из копии убирает старые
  миниатюры и хранит только 3 прежние базы; фичи находят встречи по формам слова («платежам» для «Платежи»);
  закрытая карточка фичи не открывается снова; редактор шаблонов спрашивает, прежде чем выбросить правки; язык
  интерфейса сохраняется при любом порте запуска; откат обновления проверяет хеши файлов, uv закреплён и
  проверяется, окно программы открывается по одноразовому адресу.

## 0.8.24

- **Следующая встреча на виду**: под приветствием карточка «Следующая через 12 мин · название» (оранжевая
  за 5 минут, во время встречи — «идёт · осталось 25 мин») и цифры дня; на линии «сейчас» недели — «→ 12 мин».
- **Новые виджеты**: «Перед встречей» (кто, когда, что открыто с прошлых встреч, бриф), «Горит сегодня»,
  «Свободное время» (окна от 30 минут), «Нагрузка недели» (часы по дням и ваша норма), «Серии без отдачи».
- **Темы оформления**: Настройки → Общие → Оформление — цвет акцента и фона из наборов.
- Прогресс периода рядом с датами; плитка с датой открывает календарь недели; на неделе названия встреч
  целиком; дроби через точку.
- Время на дэшборде идёт само, в том числе после разворачивания окна; «Через минуту: …» исчезает, когда
  пошла запись.
- **Заметки Obsidian по папкам с датой**: с «Папками по дате» заметки ложатся в папку своей даты, созданные
  раньше переносятся сами (ход виден в трее) и возвращаются, если выключить.
- «Папка автоимпорта» теперь называется «Папка автоимпорта аудио и видео».

## 0.8.23

- **Одна красная кнопка для записи**: её меню ▾ записывает с набором, с субтитрами и переводом, включает
  диктовку и открывает настройки записи. Вкладки «Студия» и больших кнопок на дэшборде больше нет; экран
  записи виден в верхней панели только пока она идёт — с текстом, заметками и участниками.
- **Расшифровка начинается сразу под заголовком**: распознавание — одна кнопка «версии и действия ▾»,
  главы только на дорожке плеера, «Без запинок» и «Автопрокрутка» — в меню вида.
- **Анализ**: над разделом три кнопки — «Пересоздать», «Копировать», «⋯»; экспорт, настройка обзора,
  сомнительные слова и вопрос о записи — в «⋯».
- **Подробности на дэшборде**: решения сгруппированы по встречам, строки спокойнее; цифры периода на одной
  линии.

## 0.8.22

- **Доступ агента (MCP) на Windows**: русский текст больше не приходит агенту знаками «�», а поиск
  по-русски находит встречи (сервер теперь всегда говорит в UTF-8, какая бы кодировка ни стояла в системе).

## 0.8.21

- **Подробности на дэшборде**: каждая цифра и виджет открывают панель с тем, из чего они состоят — встречи
  периода (решения, задачи, сколько вы говорили, часы по фичам), все решения, мои задачи, человек (встречи
  вместе, кто кому должен).
- **«Жду от других»**: виджет и список того, что обещали вам, сколько дней висит.
- **Встречи без итогов**: без решений и задач, вы почти молчали, серия без отдачи — счётчик на дэшборде и
  фильтр в списке встреч.
- **Доступ агента (MCP)**: Claude или другой агент сам ищет по встречам, читает разделы, решения и задачи;
  только чтение, записи «только локально» не отдаются. В Настройках → Экспорт готовые строки для Claude
  Desktop и Claude Code.
- **«Выжимка (~5 мин)»** в меню экспорта: моменты решений, задач и начала глав одним файлом, из анализа.
- **Задачи читаются понятнее**: проверка каждой задачи переписывает её одним понятным действием или
  отбрасывает.
- **Очередь**: «Пауза» / «Продолжить» и «Отменить все»; ждущую задачу любого вида можно убрать сразу.
- **Два режима**: «Не мешать на встречах» (анализ ждёт только во время встречи) и «Только запись» (везде,
  пока не выключите, или на 30 мин – до конца дня), оба в меню трея; меню трея стало коротким.
- **Кнопки мыши «Назад» / «Вперёд»** ходят по экранам программы, а не на страницу загрузки.

## 0.8.20

- **Дэшборд: прошедшее время закрашено.** Сегодня: шкала до «сейчас», толстая линия со временем, у прошедших
  встреч галочка, идущая встреча красная — сколько прошло и сколько осталось минут. Неделя: прошедшие дни
  закрашены целиком, сегодня — до черты со временем после последнего начавшегося события.
- **Выбор фичи у записи**: клик выбирает и закрывает список, фича подсвечивается в шапке; в списке выбранные
  обведены рамкой и отмечены галочкой.
- **Obsidian: «Реэкспорт всех расшифровок»** — все записи или только без заметки, и «Дополнить недостающее»:
  где есть расшифровка, но нет обзора, задач или глав, их допишет модель анализа (в очереди, по одной, не во
  время встреч) и заметка пересохранится.
- **Панель моделей**: загруженная модель (gemma) больше не показывает 0,5 ГБ — не меньше размера её файла.

## 0.8.19

- **Автоанализ после расшифровки снова работает**: Ollama теперь выключается вместе с программой, и выключенная
  Ollama принималась за «нет модели анализа». Теперь она запускается сама, если модель скачана.
- **Анализ — только когда нет встречи**: пока идёт запись или по календарю встреча, анализ не запускается, а
  начатый останавливается, и модель выгружается из памяти, чтобы компьютер не тормозил. Записи разбираются
  сами через две минуты после встречи (Настройки → После расшифровки).
- **Режим экономии (только запись)** в меню значка в трее и в Настройках → Общие: модели выгружаются,
  расшифровка, анализ и субтитры ждут; внизу окна надпись, нажатие выключает режим.
- **Меньше нагрузки на процессор**: GigaAM и Parakeet на процессоре берут половину ядер (от 2 до 8), а не все;
  число можно выбрать. «Включать субтитры при начале записи» можно выключить — субтитры Teams всё равно
  сохраняются с записью. GigaAM и Parakeet можно по отдельности оставить на процессоре.
- **Obsidian: в заметке всё** — расшифровка, обзор, задачи, главы, решения, письмо, конспект, свои шаблоны и
  ответы; новое дописывается сразу после генерации. Оглавление со ссылками, время в главах ведёт на строку
  расшифровки, раздел «Участники» (кто сколько говорил, длинные монологи, перебивания) и метки вокруг каждого
  раздела для агентов (`<!-- verbaliox:tasks:start -->`, список в свойствах заметки). «Сохранить все записи»,
  а при включении автоэкспорта сохраняются и прежние записи.
- **Звонок во время встречи из календаря** больше не получает её название: с встречей сравниваются те, кто
  говорил, название и приложение звонка; звонок другого человека называется «Звонок: Имя».
- **Напоминание о записях, расшифровку которых отменили**: на дэшборде («Расшифровать все», «Не напоминать») и
  уведомлением раз в день, никогда во время встречи.

## 0.8.18

- **Дэшборд вместо «Сегодня» и «Задачи»** — первая страница программы: дата и приветствие, период (неделя,
  месяц, квартал) и фильтр по фиче; виджеты с цифрами периода, встречами сегодня с автозаписью, неделей, моими
  задачами, фичами с активностью за 8 недель, временем во встречах, людьми, с кем чаще всего, решениями из
  анализов, сводкой периода локальной моделью, недавними записями и тем, что в работе. «Настроить»:
  перетаскивание, размер (S · M · L · W), убрать и добавить виджеты; набор хранится на компьютере.
  Считаются только мои задачи («Это я»), чужие остаются на странице «Задачи».
- **Obsidian: заметки по папкам фич** (включено) и {feature} в шаблоне имени файла; при смене фичи заметка
  переезжает; фичи в свойствах заметки и тегом.
- **Запись**: круглая красная кнопка справа в верхней панели; во время записи — время и «Стоп».

## 0.8.17

- **Запас памяти для системы** («Настройки → Общие»): ОЗУ и видеопамять, которые программа и модели не
  занимают. «Авто» по объёму компьютера (ОЗУ: 2 ГБ при 8, 4 при 16, 6 при 32, 8 больше; видеопамять 0,5 ГБ,
  на картах от 12 ГБ — 1 ГБ). Ollama и рабочие процессы ограничены остальным, Ollama оставляет запас карты
  свободным, при нехватке свободной памяти простаивающие модели выгружаются; если модели не хватило памяти,
  об этом сказано словами.
- **Имена в анализе следуют за правкой**: переименованный участник записи или исправленное имя контакта
  переписываются в анализах и задачах в нужном падеже («Ярослава Мельника» → «Ярослава Мельникова»).
- **«Это другой человек…»** по клику на человека в анализе: все упоминания и задачи записи переходят на
  выбранного участника или контакта (с «Отменить»).
- **Слово в словаре можно исправить**: само слово, варианты и категорию («Изменить» или двойной клик).
- **Вкладка «Анализ» показывает, что анализ идёт**: значок вращается, рядом пульсирует точка.
- **Запись**: нет ложного «звука компьютера не слышно» после звонка в другом окне; очистка голоса после
  долгого звонка показывает прошедшее время (а со второго раза и долю готового).

## 0.8.16

- **Один человек — один блок текста**: реплики одного участника подряд больше не дробятся на строки с повтором
  имени. Имя и время показываются один раз, фразы идут сплошным текстом; длинный блок делится на абзацы после
  паузы в речи или когда абзац затянулся, у каждого — время слева. Каждую фразу по-прежнему можно поправить
  (карандаш при наведении или двойной клик), при воспроизведении подсвечивается текущая фраза, клик по слову
  перематывает. Участник всего блока меняется в его заголовке, одной фразы — правым кликом «Эту фразу сказал…»,
  там же «Изменить фразу» и «Соединить с предыдущей фразой».

## 0.8.15

- **Медиатека таблицей на всё окно**, как столбцы в проводнике Windows: кнопка рядом с «Медиатека». Название,
  фича, дата, длительность, участники, язык и состояние; по выбору дата добавления, размер файла, модель
  распознавания, открытые задачи и папка («Столбцы», «Вернуть как было»). Клик по заголовку сортирует, край
  заголовка меняет ширину; группы по дням, фичам или папкам; поиск и фильтр по фиче. Клик выбирает (Ctrl и
  Shift — несколько), двойной клик или Enter открывает, правый клик — меню записи, строку можно перетащить
  в папку.
- **Фича в медиатеке**: цвет и название рядом с названием записи; в компактном списке — цветная точка на
  одном месте у всех строк.
- **Скачанная модель анализа больше не числится нескачанной** после перезапуска: пока Ollama остановлена,
  её модели читаются из её папки, а анализ запускает её сам.

## 0.8.14

- **Контакты**: кнопка в боковой панели открывает всех людей, которых знает программа. Карточка человека:
  открытые задачи (каждую можно передать другому), записи, где он говорит, где его упоминают и куда его
  приглашали, и «+ Задача». Анализ и поиск задач знают контакты, а не только участников встречи.
- **Каждое упоминание человека размечено** в анализе и задачах: контакт — ссылка на карточку; неясному имени
  программа предлагает контакт, как фичу («Дмитрий Орлов?» с ✓ и ✕); имя не из контактов можно добавить или
  указать, кто это; имя, которого нет и в расшифровке, — красное: модель могла его придумать.
- **Полные имена**: модель пишет людей так, как они записаны в контактах, а не «Дима»; подтверждённая короткая
  форма заменяется полным именем в анализе записи.
- **Меньше сомнительных слов**: без частых слов («и», «в», «что»), без расхождений в окончаниях и без слов, которые
  модели одинаково расслышали в других местах; кнопка скрывает подчёркивания.
- **О новой версии сообщается**: уведомление Windows, отметка в боковой панели до установки, «Что нового» перед
  обновлением и один раз после него.
- **Запись**: звуковой сигнал за минуту до автозаписи встречи, при начале и после остановки (в запись не попадает;
  «Настройки → Запись»); запись по календарю останавливается, когда звонок закончился раньше времени.
- **День на странице «Сегодня»**: встречи в одно время стоят рядом, общее время заштриховано; полные названия при
  наведении.
- **Словарь** открывается в своём окне; в **панели моделей** выбирается, через сколько выгружать модель без дела,
  таймер не переносится.

## 0.8.13

- **Первый запуск — одна тема на шаг**: ИИ-анализ; звук (микрофон и звук компьютера, только микрофон или
  только компьютер, микрофон с проверкой уровня, фильтр шума); автозапись звонков с выбором программ и
  субтитры Teams (Windows); календарь (Outlook или ссылка) и запись всех встреч из него; затем что
  скачается, с точным режимом и «Запускать вместе с Windows». Неверный адрес календаря больше не сбрасывает
  остальные выборы.
- **Точный режим берёт все модели распознавания**, а его список показывает каждую модель отдельной строкой
  с состоянием и кнопкой «Скачать» у ещё не скачанной.
- **Модели анализа: в списке только Gemma 4 E4B и Gemma 4 E2B.** В замерах на реальных встречах одна из
  них находит больше задач, быстрее и в меньшей памяти, чем Qwen3.5 4B, Qwen3 8B, Qwen3 14B и Qwen Lite.
  Уже скачанная Qwen остаётся в списке и работает. Если модель не выбрана, берётся Gemma 4 E2B.
- **Карточки моделей**: размер, лицензия и оценки всегда на виду; описание открывается по «i» или по клику
  на карточку. Описания говорят, что это за модель и какие у неё замеры. Оценки (точность, качество,
  скорость, нагрузка) следуют замерам, шаг — половина точки, у двух моделей они не совпадают.
- **Панель моделей**: каждая модель с новой строки (без мерцания под курсором), легенда под «i», плотный
  фон.
- При облачной модели локальные подписаны «для перевода и дубляжа»: они всегда работают на этом
  компьютере.
- **Сборка ONNX Runtime для видеокарты**: файл, который антивирус держит при переименовании, больше не
  срывает установку (WinError 5); программа берёт новую папку и заканчивает замену при следующем запуске.
- Настройки: «Для опытных» теперь называется «Эксперименты».

## 0.8.12

- **Первый запуск**: окно больше не падает, пока WebView2 создаёт профиль (сервер стартует, когда окно
  готово); значок в трее и автозапуск работают с первого запуска.
- **Установщик использует скачанный Python**: если Windows запрещает ссылку, которую uv делает в папке
  программы, окружение создаётся прямо из этого Python, а не из системного.
- **Окно настройки**: найденный Ollama отмечен зелёной точкой; если его нет — тёмный флажок (отмечается
  кликом по всей строке) вместо белого квадрата.

## 0.8.11

- **Анализ по шагам** (включён по умолчанию, «Настройки → ИИ-анализ»): сначала решения и открытые вопросы,
  потом задачи по всей расшифровке, потом протокол. Его «Решения», «Открытые вопросы» и «Следующие шаги» —
  те же списки слово в слово, поэтому обзор и задачи всегда сходятся. Задача, найденная позже (пересчёт
  задач), дописывается в «Следующие шаги». Замер на 8 эталонных записях: задач находится столько же и
  точнее, расхождений нет, на часовую запись около 12 с дольше.
- **Правка анализа вручную**: выделите слово → «Исправить…» — оно исправится во всех разделах записи;
  «Править» открывает раздел как Markdown. Правильное написание попадает в словарь, а прежнее — его
  вариантом: распознавание и следующие анализы пишут его верно.
- **Сомнительные слова подчёркнуты** в анализе: где модели распознавания расслышали по-разному или Whisper
  не уверен. По клику — другое написание, место в записи или «Верно». «Проверить слова моделью» (⋯) — маленькая
  локальная модель ищет искажённые термины и имена.
- **Длинные записи быстрее и без обрывов**: конспекты частей пишутся без рассуждений, а на видеокарте от 8 ГБ
  у ответа вдвое больше места — ответы больше не обрываются и не переспрашиваются.
- Английская встреча получает задачи по-английски, а безымянные участники в обзоре — «Speaker N».
- Вкладка «Следующие шаги», повторявшая задачи, убрана (остаётся там, где уже создана).
- Настройки: «Перед очными встречами спрашивать» переключается всегда; подпись говорит, что он действует
  вместе с записью всех встреч.
- **Ollama больше не остаётся в памяти после закрытия программы**: запущенный программой Ollama
  завершается вместе с ней (и при сбое); Ollama, запущенный вами, продолжает работать, но выгружает модели.
- **Удаление всего**: `uninstall.bat` в папке программы («Удалить Verbaliox полностью» в меню «Пуск»)
  удаляет программу, данные, модели, автозапуск, ярлыки и временные файлы — и у переносной, и у
  установленной копии. Про Ollama, uv и Python спрашивает отдельно; выбранные вами папки (записи в другом
  месте, экспорт, Obsidian) остаются.

## 0.8.10

- **Общий контекст у всех вкладок анализа записи**: поиск задач получает из протокола решения и следующие
  шаги (решение-действие становится задачей, если прозвучало в расшифровке); протокол и остальные вкладки
  (короткая выжимка, письмо по итогам, «Мои заметки», свои шаблоны) получают найденные задачи, а остальные
  вкладки — ещё и решения, открытые вопросы и следующие шаги протокола. Уже разобранные записи меняются
  после «Пересоздать».

## 0.8.9

- **Обновление клона git из программы**: «Обновить через git» в Настройки → Общие → Обновления запускает
  update.bat (новая версия и нужные пакеты), программа закрывается на время обновления и запускается снова.
- **Протокол — сначала результат**: краткое содержание, решения, новые «Открытые вопросы», следующие шаги,
  затем обсуждение по темам и упомянутые детали.
- **«Сегодня»** держит выбранный рабочий день: событие на весь день или долгое больше не показывает ночь с
  00:00; встреча чуть за краями растягивает день не больше чем на два часа.
- **Страница «Задачи»**: строки переносятся по ширине самого списка (при открытой сводке текст заходил под
  исполнителя); задачи, которые модель отдала «team» или «none», — без исполнителя.

## 0.8.8

- **Импорт без распознавания**: «Только добавить, без распознавания» в окне импорта кладёт файлы (или
  скачанное по ссылке) в медиатеку; кнопка «Распознать» у записи запускает распознавание, когда нужен текст.
- **Точный режим в окне импорта** — под моделью распознавания, а не за «Изменить»; включённый в настройках
  без отмеченных моделей, сам отмечает GigaAM v3, Whisper Pro и Parakeet TDT v3; подсказка объясняет, что
  такое «основная модель».
- **Спорное слово говорит, кто выбрал вариант**: модель анализа по смыслу соседних слов или самая точная
  модель, если модель анализа это место не решила.
- **Панель «Модели»**: у работающей модели видно, через сколько минут она выгрузится сама; при наведении
  плашка говорит, что сделает клик («Выгрузить ×» красным, «Запустить ▷»).
- **Фичи**: в шапке записи — справа, на одном месте, после «Фича:»; окно выбора остаётся под ними после
  создания фичи; в медиатеке у фич своя кнопка рядом с фильтрами.
- **Карточки задач**: «Исполнитель» перед именем, «для» перед тем, кому задача нужна.
- **Живые субтитры**: быстрый режим берёт Gemma 4 E2B (замер en↔ru: почти как E4B по качеству, ~0,4 с на
  фразу); модели, не разрешённые для коммерческого использования, больше не выбираются.
- Тёмные чекбоксы везде; без синих точек у разделов настроек; мягче тень окон; рамка выбранного списка
  больше не обрезается; «Окружение дубляжа работает» — зелёное уведомление, а не красная ошибка.

## 0.8.7

- **Фичи**: встрече можно указать фичу, к которой она относится (одну или несколько). Серия может
  ставить фичу своим новым встречам сама; название встречи в Teams и модель анализа подсказывают фичу
  (✓ / ✕). Медиатека и страница «Задачи» фильтруют и группируют по фичам; страница фичи собирает её
  встречи, их решения и открытые задачи, с ассистентом по ним. Настройки → Словарь → Фичи: цвет,
  описание, ключевые слова и термины (они помогают распознаванию и моделям).
- **MFU организатора**: итоги из чата Teams вставляются в запись; задачи из них берутся как написано, а
  протокол на них опирается. На каждой карточке задачи видно, откуда она: MFU, LLM или ✎.
- **Задачи — карточками**: исполнитель и срок открывают свои списки; краткое имя, сказанное на встрече
  («Макс», «Дима»), находит участника, записанного в Teams полностью; имя с опечаткой — имя участника.
- **Gemma 4** — модель анализа по умолчанию (E4B для видеокарт от 8 ГБ, E2B — для меньших), на 8 ГБ
  читает 32k контекста за раз и делит видеокарту с распознаванием. Программа скажет, если для неё нужно
  обновить Ollama.
- **Nemotron 3 Diarization** (NVIDIA, OpenMDW-1.1) — на выбор для разделения участников; заданное заранее
  число участников соблюдается лучше.
- **Облачный анализ работает с текущими моделями**: Claude, новые модели OpenAI и Gemini получают
  запросы, которые принимают; обрезанный, отфильтрованный или отклонённый ответ показывается ошибкой, а не
  сохраняется; снятая модель заменяется моделью того же семейства; каждая отправка видна в журнале.
  Gemini на бесплатном ключе может не успеть написать протокол часовой встречи за 10 минут, которые
  ждёт программа.
- **Задачу можно отдать любому из «Все люди»** (справочник людей), а не только участникам встречи;
  ввод имени сужает список. Вариант имени, объединённый в справочнике («Лёля» с «Ольга Смирнова»),
  находит своего человека в задачах, которые нашла модель.
- **Nemotron**: в «Авто» группа обрывков (несколько секунд в длинной записи) больше не считается
  участником; на видеокарте работает в bf16 — быстрее и с меньшим расходом памяти.
- **Настройки помещаются в узкое окно**: разделы становятся колонкой значков, поля — одно под другим.
- **Глоссарий** вмещает около сотни терминов на фичу и не повторяет термины фичи этой встречи; место
  для расшифровки учитывает описание фичи и глоссарий. Панель «Модели» показывает настоящий размер
  загруженной Gemma 4.

- **Настройки — 7 вкладок вместо 14**: бывшие вкладки стали разделами (Обновления и О программе — в
  Общих, Горячие клавиши и Календарь — в Записи, Модели речи и Словарь — в Распознавании, Сравнение моделей
  и Дубляж — в «Для опытных»). Старые ссылки открывают нужный раздел.
- **Бриф перед встречей.** На «Сегодня» у встречи, которая продолжает серию, есть «Бриф · N» (открытые
  задачи); за пять минут до неё уведомление открывает бриф.
- **Расшифровку Teams (.vtt)** можно добавить к записи (её меню ⋯): отдельная версия, а её имена получают
  голоса, которые ещё называются «Участник N».
- **«Указать файл…»** у записи, чей файл переместили; файл проверяется по длине.
- **Плейлисты**: ссылка на плейлист или канал спрашивает, скачать всё (каждое видео — запись в своей
  папке) или только первое видео.
- **Запись надёжнее.** Звук компьютера переходит на устройство вывода, которое выбрала Windows
  (подключили гарнитуру посреди звонка); если во время звонка звука компьютера нет минуту, студия скажет
  сразу. Запись, у которой закрыли или перезагрузили окно, сохраняется сама вместе с заметками; после
  сбоя её части становятся одной записью с заметками. Длинные записи сводятся при любой длине с одним и
  тем же расходом памяти (~150 МБ) и показывают ход.
- **Перетащенные в окно файлы добавляются на месте**, без копии; файл, который уже есть в медиатеке,
  второй раз не добавляется.
- **Очередь**: только что записанная встреча расшифровывается раньше дубляжа и перевода; отмена записи,
  ждущей в очереди, срабатывает сразу.
- **Экраны проще**: эхо и очистка голоса включаются сами (переключатели — в Настройки → Запись →
  Дополнительно); в строке субтитров студии остались «Субтитры» и «Перевод», остальное — под шестерёнкой;
  ассистент без модели говорит об этом один раз; задачи помещаются в узкое окно.
- **Исправления после тройного аудита**:
  - облачная модель не используется без вашего согласия;
  - записи папки «только локально» остаются защищёнными, если папку удалить;
  - ссылки в тексте ИИ открываются в браузере, а не в окне программы;
  - календарь учитывает часовые пояса в Windows (названия зон Outlook, летнее время других стран),
    перенесённые встречи серии, «первый понедельник месяца» и 31-е число;
  - правки во время «Разделить заново» больше не теряются;
  - ошибки объясняются понятными словами;
  - экспорт в Word принимает текст, вставленный из Word;
  - срок хранения звука считается с момента, когда запись попала в программу;
  - обновление, скачанное до выхода более новой версии, скачивается заново;
  - продиктованный текст не попадает в журнал буфера обмена;
  - большие медиатеки открываются быстрее.

## 0.8.6

- **Голоса больше не звучат дважды на записях через колонки.** Захват звука компьютера терял куски,
  когда программа была занята (Windows сообщала об этом тысячи раз за встречу), и вставлял тишину там,
  где звук просто пришёл с опозданием: дорожка уезжала относительно микрофона. Теперь тишина вставляется
  только там, где звука правда нет, потерянные куски восполняются, а дорожка не обгоняет реальное время.
- **ИИ-очистка голоса в микрофоне** (DeepFilterNet 3, MIT / Apache 2.0): при сохранении записи из
  микрофона убирается шум — вентилятор, клавиатура, улица, — голос остаётся. Фильтр (27 МБ) скачивается
  в Настройки → Запись или в студии, в блоке «Автоматически».
- **Импортированные файлы остаются на месте**: «Файлы…» открывает окно выбора Windows и добавляет файлы
  по их пути, без копии. Копирование можно включить в Настройки → Запись.
- **Выгрузка модели анализа при загруженной видеокарте** ждёт дольше, находит её процесс и сама
  повторяется, пока видеокарта не освободится.
- Компактный вид встречи Teams больше не считается другой встречей; закрытие окна Teams больше не
  обрывает поиск субтитров.

## 0.8.5

- **Запись следит за встречей в Teams.** Перешли в другую встречу — запись сохраняется и начинается
  новая, названная по этой встрече; встреча закончилась (её окна нет 30 секунд) — запись
  останавливается. Teams не отпускает микрофон между встречами, и первая запись шла через вторую.
  Встречей считается только окно с кнопкой выхода из звонка: переключение чатов в главном окне ничего не
  перезапускает. Переключатель — в студии, в блоке «Автоматически».
- **Имена участников в анализе.** Сводка, главы, шаблоны, вопросы к записи и поиск задач получают
  список тех, кто был на встрече (названные говорящие, пометки в студии, субтитры Teams, приглашённые из
  календаря — в написании из «Все люди», с должностью), и пишут имена так же; имя, всё же написанное с
  ошибкой в одну-две буквы, исправляется с сохранением падежа.

## 0.8.4

- **Голоса больше не звучат дважды на записи через колонки.** Звук компьютера и микрофон могли
  разъехаться на десятки секунд (голос было слышно повторно, «из будущего»); эхо искалось только в
  пределах 2 секунд, и дорожки не выравнивались. Теперь сдвиг сначала ищется по громкости обеих дорожек,
  до 90 секунд и по всей записи, затем уточняется; в журнале видно, насколько разошлись дорожки и сколько
  тишины вставил захват звука компьютера.
- **«Выгрузить всё» останавливает и анализ.** Сводка, главы или ответ ассистента, которые сейчас
  пишутся, показаны как занимающие модель; выгрузка спрашивает и сразу их останавливает, а не даёт
  следующей части снова загрузить модель.
- **Субтитры в студии:** кто говорит — на каждой строке, как в Teams: имя и кружок с инициалами цвета
  человека.
- **Своё фото человека** («Фото…» на карточке участника, 📷 в «Все люди») показывается вместо инициалов
  на карточках, в справочнике и в субтитрах студии.

## 0.8.3

- **«Разделить по голосам» в панели распознавания**, рядом с моделями, а не только на вкладке «Участники».
- **Знак ИИ** на кнопках, которые запускают модель: «Расшифровать», «Свести всё», «Разделить по
  голосам». «Без запинок» работает по списку, без модели, и потерял иконку-искорку.
- **Субтитры в студии:** если прокрутить вверх, текст больше не перематывается в конец с каждой новой
  строкой; кнопка «↓ К новым репликам» возвращает вниз.
- **Имена из Teams в студии** теперь стоят и у строк длинного монолога (строка Teams длится, пока
  человек говорит) и появляются сразу, как приходят субтитры Teams.
- **Медиатека:** синим выделено только то, что открыто. В студии подсвечена идущая запись, а последняя
  открытая — лишь лёгкой меткой; при открытии другой записи идущая отходит на второй план.
- **Щелчок по уведомлению открывает то, о чём оно:** готовую запись, студию с идущей записью, только что
  сохранённую запись или настройки неработающей горячей клавиши.

## 0.8.2

- **«Разделить заново» на вкладке «Участники».** Реплики заново делятся по голосам без повторного
  распознавания текста: укажите, сколько людей говорило самое большее, или доверьте это голосам.
  Исправленные вами реплики остаются целыми с вашим текстом; имена возвращаются из запомненных голосов,
  пометок в студии, субтитров Teams и тех, что вы уже дали. Подходит для записей до 0.8.1, где все
  оказались одним участником.

## 0.8.1

- **Участники снова различаются.** В созвоне всегда есть фразы, которые не похожи ни на чей голос
  (смех, шум, обрывок слова). Каждая становилась отдельным участником, поэтому при указанных шести
  участниках (из календаря или субтитров Teams) вся встреча доставалась одному человеку, а без числа
  она тоже выходила одним участником. Теперь такие фразы откладываются при разделении по голосам и потом
  получают ближайший голос.
- **Число участников — это максимум.** Число из календаря или субтитров считается верхней границей:
  если пригласили десятерых, а говорили двое, участников будет двое.
- Голоса разных людей, прошедшие через один кодек созвона, больше не сливаются в один.
- Имена из субтитров Teams теперь достаются разным голосам, каждому своё.

## 0.8.0

Выпуск исправлений и ускорений после независимого аудита всего кода тремя моделями.

- **«Стоп» мгновенный.** Запись сразу в медиатеке («Сведение дорожек») вместе с заметками, отметками
  и субтитрами Teams; удаление эха и сведение идут в фоне, потом запись сама встаёт на расшифровку.
  Закрытие программы во время сведения предупреждается; при сбое сведения части не теряются.
- **Запись надёжнее.** Сорвавшийся старт больше не оставляет запись звука компьютера; «Стоп» во время
  запуска её останавливает; обрыв захвата звука компьютера виден сразу; кусочки записи
  пронумерованы (без повторов и перестановок, задержка видна и повторяется две минуты, потерянный
  кусочек больше не обрывает остальное); запись только с микрофона перематывается; «Сохранить звук» и
  нарезка не уничтожают заменяемый файл.
- **Субтитры Teams:** не замедляются к концу долгой встречи, строки, бывшие на экране до записи, не
  дают голосам чужие имена, короткое «Да» не затирает прежнюю реплику, включённые посреди встречи
  субтитры учитываются, один поток чтения; пока субтитров нет, поиск панели реже.
- **Точный режим** сохраняет ваши правки в тексте основной модели, берёт версии других моделей только
  сделанные так же, сохраняет язык, переживает отмену и перезапуск.
- **Модели и память:** расшифровка не выгружает модель живых субтитров; Whisper, откатившийся на
  процессор, так и помечается; модель анализа держится по настройке (сразу выгружается только для
  расшифровки); принудительная выгрузка закрывает только процесс этой модели; удаление эха берёт
  ~2 ГБ меньше; словарь в 5 раз быстрее; статус, плеер и опрос моделей не читают всю расшифровку;
  части длинной записи читаются один раз для обзора и глав.
- **Редактирование:** набранный текст переживает перерисовку; щелчок по другой записи не теряется;
  с «Без запинок» подсвечивается то слово, что звучит; правки ждут во время сведения версий; имена,
  данные на экране, остаются после «Свести версии».
- **Безопасность:** текст модели анализа больше не может вызвать функции страницы.
- А также: «Показать в папке» не открывает сетевые пути; отмеченные задачи остаются выполненными;
  отменённая первая расшифровка оставляет найденную поиском часть; поиск по смыслу учитывает правки
  во время индексации; папка наблюдения не берёт записи самой медиатеки; служебные файлы отменённых
  заданий удаляются.

## 0.7.10

- **Запись через колонки больше не звучит как два человека одновременно:** звук компьютера ставится в
  сведение туда, где его услышал микрофон (это измеряется по самому звуку, а не по отметкам начала
  дорожек), а эхо колонок отслеживается по всей записи, со скачками.
- **«Показать в папке» выделяет файл**, а не открывает «Документы» (Проводник путался из-за пробела в
  пути).

## 0.7.9

- **Студия: у строк живых субтитров видно, кто говорит** — по субтитрам Teams (совпадают слова и время)
  или по последней отметке «Сейчас говорит»; имя стоит над строкой, когда говорящий сменился.
- **Из субтитров Teams берутся готовые фразы:** Teams переписывает строку, пока её произносят; теперь
  каждая фраза сохраняется один раз, в окончательном виде, а не все промежуточные варианты.
- «Проверить» в «Настройки → Запись» во время записи показывает последние прочитанные строки.
- Медиатека: панель нескольких выбранных записей исчезает вместе с выбором (щелчок по записи, ✕ или Esc).

## 0.7.8

- **Субтитры Teams снова читаются:** компонент Windows для чтения окон (UI Automation) не загружался
  («Could not load file or assembly 'UIAutomationClient'»); теперь он загружается по полному имени или из
  своего файла. Кнопка «Проверить» в «Настройки → Запись» показывает, видны ли субтитры.

## 0.7.7

- **«Все модели» в панели «Распознавание»:** при выборе подсвечиваются модели, которые будут работать,
  а в статусе — их порядок; «Распознать точно» запускает их и сводит версии. Модель, у которой уже
  есть текст этой записи, повторно не запускается — её версия берётся как есть.
- **Статус показывает, какая модель работает сейчас** (а не «Авто: по языку»), в точном режиме — каждую
  по очереди.
- **Субтитры Teams находятся надёжнее:** выбирается панель со строками, а не кнопка «Параметры
  субтитров», и в большом окне встречи тоже. Кнопка «Проверить» в «Настройки → Запись» показывает, что
  программа видит в Teams прямо сейчас, без записи.
- **«Никогда для этой встречи и её повторов»** в вопросе перед встречей из календаря; вернуть можно на
  главной.

## 0.7.6

- **Кто говорит — со встречи.** В студии появился блок «Участники»: сколько людей на встрече (гости из
  календаря подставляются) и отметки «Сейчас говорит» — щелчок по имени, пока человек говорит, подпишет
  его голос после расшифровки.
- **Субтитры Microsoft Teams (по желанию, «Настройки → Запись», по умолчанию выключено).** Во время записи
  имена над живыми субтитрами Teams читаются так же, как их читает экранный диктор Windows (ничего не
  нажимается и никуда не отправляется): участники сами появляются в студии, голоса получают настоящие
  имена, а субтитры сохраняются отдельной версией текста (значок «Субтитры Teams»). Как включить субтитры
  в Teams — в программе и в docs/teams-captions.md.
- **Панель «Распознавание» показывает модели значками** с состоянием их текста (готов, нет, идёт, не
  скачана) и кнопкой «Свести всё»; при показе сведённого текста подсвечиваются модели, из которых он
  собран. Whisper Pro всегда входит в точный режим; мастер первого запуска умеет включить точный режим,
  с пометкой «рекомендуется для наилучшего качества».
- **Память:** перед ответом модели анализа выгружаются простаивающие модели распознавания (и модель
  субтитров), а сама модель анализа уходит из памяти через 20 с после последнего ответа.
- **Участники:** указанное число в одного-двух человек исправляется, если голосов явно три и больше.
- **Живые субтитры** больше не прыгают, когда окно разворачивают после долгого сворачивания.
- **Остановленная запись остаётся в медиатеке** с пометкой «сохраняется», пока сводятся дорожки (у
  долгой встречи — пару минут), а не пропадает до готовности.

## 0.7.5

- **В памяти одна модель за раз.** Точный режим запускает модели распознавания по очереди, выгружая
  каждую перед следующей; модели распознавания выгружаются перед моделью анализа, а модели анализа —
  перед распознаванием. Ollama держит одну модель (кроме живых субтитров с переводом).
- **Точный режим выбирается в панели «Распознавание»** у записи: «Точный: все модели + сведение» рядом с
  моделями. Панель всегда видна в своей рамке, а не сворачивается в маленький значок.
- **Спорное слово показывает, кто выбрал вариант:** модель анализа по смыслу или самая точная модель,
  если модель анализа это место не решила.
- **Запись, начатая или остановленная сама (звонок, встреча из календаря), показывает уведомление
  Windows** — что записывается и как остановить.
- **Участники:** имя приглашённого, которое уже есть у участника, остаётся в подсказках и объединяет двух
  участников; если вписать его вручную — то же предложение. Объединение во «Всех людях» показывает, что
  идёт работа.
- **Медиатека:** по умолчанию компактный список по дням; дни выглядят как разделители, «Сегодня» — голубым.

## 0.7.4

- **Точный режим: несколько моделей + сведение** («Настройки → Распознавание» и переключатель у записи
  в окне импорта). Каждая новая запись распознаётся ещё и другими скачанными моделями, а версии сводятся
  в одну: где модели услышали разное, модель анализа выбирает вариант по смыслу соседних слов, порциями.
  Версия каждой модели остаётся в списке над текстом.
- **Запись через колонки больше не двоится.** Системный звук начинался раньше микрофона и терял паузы,
  поэтому голоса звучали дважды, второй раз с опозданием; теперь дорожки совпадают. А эхо колонок,
  которое слышит микрофон, вычитается при сохранении записи («Настройки → Запись», включено; в
  наушниках ничего не меняется).
- **Отмена и «Выгрузить» работают как рубильник.** Отмена срабатывает сразу, даже посреди обзора;
  свободная модель выгружается сразу, занятая — после остановки, которую вы подтверждаете.
- **Студия:** живые субтитры не отстают после сворачивания окна; при выключении и включении субтитров
  строки остаются, а «Вопросы» видят всю запись; плашка записи помещается при любой ширине и масштабе.
- **Медиатека:** идущая запись видна строкой сверху со временем; по клику открывается студия с
  субтитрами.
- Анализ называет участников так, как они подписаны в расшифровке, а не «Пользователь» или выдуманным
  именем.

## 0.7.3

- **Словарь работает со всеми моделями распознавания.** Раньше его учитывал только Whisper, и то как
  подсказку, а GigaAM и Parakeet не видели совсем. Теперь после распознавания (записи, живые субтитры,
  диктовка) слово из словаря заменяет то, что вместо него услышали: его **варианты** («как может
  распознаться»: `клод, klot` для Claude) и, если включён новый переключатель, **похожие по звучанию**
  слова на латинице и кириллице («klot», «клода» → «Claude», «в кубернетисе» → «в Kubernetes»). Живые
  субтитры на Whisper тоже получают словарь как подсказку.
- **Обзор длинной встречи охватывает её с начала.** Конспекты всех частей полуторачасовой записи не
  помещались в контекст модели, и начало молча отбрасывалось; теперь они сжимаются, пока не поместятся.
  Так же исправлены темы над таймлайном, а ключевые моменты и «С прошлого раза» больше не читают только
  начало длинной встречи.
- **Задачи:** из длинной встречи их намного меньше: каждая проверяется второй раз по сказанному, повторы
  объединяются, длинная встреча читается по частям до конца. Задачи переименованного участника получают
  новое имя.
- **Темы над таймлайном** создаются сами вместе с обзором встречи от 10 минут.
- **«Это я»** на втором участнике записи предлагает объединить его с вашей карточкой; участник с
  именем по умолчанию получает ваше имя.
- **Модель анализа больше не думает десятки минут:** ответ ограничен 3072 токенами, а обзор длинной
  записи показывает, какую часть он читает.
- **Видеокарта, для которой у PyTorch нет ядер** («no kernel image is available»): модель участников
  работает на процессоре, а не падает.
- Открытый раздел и открытая вкладка записи в верхней панели — синие.

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
