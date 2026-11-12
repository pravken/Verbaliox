"""
Requests of a job that a cancel breaks off at once. An answer of the analysis model can take minutes
(an overview of a long recording on a small model), and the job only looked at the cancel between
steps: «Stop» then waited for the answer. A request runs on a helper thread and the job waits for it
looking at the cancel every 0.2 s; on a cancel the job goes on at once (its step raises Aborted) and
on_abort stops the work behind the request (Ollama unloads the model writing the answer).
"""

import threading
from typing import Callable, Optional, Set, TypeVar

T = TypeVar("T")
POLL_SEC = 0.2

_lock = threading.Lock()
_aborted: Set[int] = set()


class Aborted(RuntimeError):
    pass


def reset(thread_id: int) -> None:
    """A new job starts on this thread: an earlier cancel no longer applies."""
    with _lock:
        _aborted.discard(thread_id)


def abort(thread_id: int) -> None:
    """The requests that thread waits on, and the ones it starts next, end at once."""
    with _lock:
        _aborted.add(thread_id)


def is_aborted() -> bool:
    with _lock:
        return threading.get_ident() in _aborted


def call(fn: Callable[[], T], on_abort: Optional[Callable[[], None]] = None) -> T:
    if is_aborted():
        raise Aborted("Обработка отменена")
    box: dict = {}
    done = threading.Event()

    def work() -> None:
        try:
            box["value"] = fn()
        except BaseException as e:  # given to the waiting thread as it is
            box["error"] = e
        finally:
            done.set()

    threading.Thread(target=work, daemon=True, name="abortable-request").start()
    while not done.wait(POLL_SEC):
        if is_aborted():
            if on_abort:
                threading.Thread(target=on_abort, daemon=True, name="abort-cleanup").start()
            raise Aborted("Обработка отменена")
    if "error" in box:
        raise box["error"]
    return box["value"]
