"""
Проверка: видно ли субтитры Microsoft Teams через интерфейс доступности Windows.

Что делает (и ничего больше):
  * раз в секунду находит окна Teams и смотрит, свёрнуты ли они;
  * ищет в них панель субтитров и читает показанные там строки — тем же способом, каким их читает
    экранный диктор Windows (UI Automation);
  * печатает найденное на экран и пишет в файл teams_probe_<дата-время>.txt рядом с этим скриптом.

Чего НЕ делает: не нажимает кнопки, не печатает клавиши, не меняет и не закрывает окна, не
внедряется в Teams, не читает его память или файлы, ничего не отправляет в интернет и ничего не
устанавливает. Файл с результатом остаётся только на этом компьютере — посмотрите его перед тем,
как кому-то отправлять: в нём текст встречи.

Как запустить (из папки программы, во время встречи с включёнными субтитрами в Teams):
    .venv\\Scripts\\python.exe tools\\teams_captions_probe.py
Остановить: Ctrl+C. Хорошо бы за 3–5 минут попробовать: окно Teams открыто; перекрыто другим
окном; свёрнуто; встреча в маленьком плавающем окне. Скрипт сам пишет, в каком состоянии окно.

Нужен только pythonnet (он уже стоит вместе с программой) и Windows 10/11.
"""

import datetime
import sys
import time
from pathlib import Path

if sys.platform != "win32":
    sys.exit("Скрипт работает только в Windows")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.teams_captions import load_uia  # noqa: E402  pythonnet: компонент Windows для экранных дикторов

load_uia()
from System.Diagnostics import Process  # noqa: E402
from System.Windows.Automation import (  # noqa: E402
    AutomationElement, Condition, ControlType, TreeScope, WindowPattern,
)

TEAMS_PROCESSES = {"ms-teams", "teams", "msteams"}  # новый Teams, классический Teams
CAPTION_WORDS = ("caption", "субтитр")             # так панель называется в английском и русском Teams
MAX_ELEMENTS = 4000                               # сколько элементов окна смотреть за раз, не больше
OUT = Path(__file__).with_name(f"teams_probe_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt")


def log(text: str) -> None:
    line = f"{datetime.datetime.now():%H:%M:%S}  {text}"
    print(line)
    with OUT.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def process_name(pid: int) -> str:
    try:
        return Process.GetProcessById(pid).ProcessName.lower()
    except Exception:
        return ""


def teams_windows():
    """Окна верхнего уровня, которые принадлежат Teams."""
    root = AutomationElement.RootElement
    for w in root.FindAll(TreeScope.Children, Condition.TrueCondition):
        try:
            if process_name(w.Current.ProcessId) in TEAMS_PROCESSES:
                yield w
        except Exception:
            continue


def window_state(w) -> str:
    try:
        pattern = w.GetCurrentPattern(WindowPattern.Pattern)
        state = str(pattern.Current.WindowVisualState)  # "Normal", "Minimized" или "Maximized"
        return "свёрнуто" if "Minimized" in state else "развёрнуто" if "Maximized" in state else "открыто"
    except Exception:
        return "неизвестно"


def describe(el) -> str:
    c = el.Current
    return f"{c.ControlType.ProgrammaticName.replace('ControlType.', '')} name={c.Name!r} id={c.AutomationId!r} class={c.ClassName!r}"


def caption_panels(w):
    """Элементы окна, в имени или id которых есть «caption» / «субтитр»."""
    found = []
    walked = 0
    for el in w.FindAll(TreeScope.Descendants, Condition.TrueCondition):
        walked += 1
        if walked > MAX_ELEMENTS:
            break
        try:
            c = el.Current
            text = f"{c.Name} {c.AutomationId}".lower()
        except Exception:
            continue
        if any(word in text for word in CAPTION_WORDS):
            found.append(el)
    return found, walked


def texts_under(el):
    """Строки текста внутри панели: то, что видно на экране."""
    out = []
    for t in el.FindAll(TreeScope.Descendants, Condition.TrueCondition):
        try:
            c = t.Current
            if c.ControlType == ControlType.Text and c.Name.strip():
                out.append(c.Name.strip())
        except Exception:
            continue
    return out


def main() -> None:
    log(f"Начало проверки. Результат пишется в {OUT}")
    seen = set()
    described = set()
    last_state = {}
    try:
        while True:
            wins = list(teams_windows())
            if not wins:
                log("Окон Teams не найдено")
            for w in wins:
                try:
                    title = w.Current.Name
                except Exception:
                    continue
                state = window_state(w)
                if last_state.get(title) != state:
                    last_state[title] = state
                    log(f"Окно Teams «{title}»: {state}")
                panels, walked = caption_panels(w)
                for p in panels:
                    key = describe(p)
                    if key not in described:  # как устроена панель — один раз, для разбора
                        described.add(key)
                        log(f"  панель субтитров: {key}  (просмотрено элементов окна: {walked})")
                    for line in texts_under(p):
                        if line not in seen:
                            seen.add(line)
                            log(f"  [{state}] {line}")
            time.sleep(1.0)
    except KeyboardInterrupt:
        log(f"Остановлено. Новых строк субтитров: {len(seen)}")


if __name__ == "__main__":
    main()
