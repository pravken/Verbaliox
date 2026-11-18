"""
Is a recording the calendar meeting going on when it was made? (Asked by the user: a person called them
directly during the time of a meeting in the calendar, and the call got the meeting's name and invitees.)

The time alone is not enough. What the recording itself says is compared with the event:
- the people heard: the names of the Teams captions or of «Сейчас говорит» at the end of the recording,
  the speakers the voices were recognized as after the transcription;
- the title the recording got (the Teams meeting window, or typed by the user);
- the app of the call: a call in a messenger (Telegram, WhatsApp, Discord) during a meeting with a link is
  another conversation.

verdict(): "yes" (the meeting: its title and invitees), "no" (another conversation: named after the people
heard, «Звонок: Анна Смирнова», or by its content), "unknown" (nothing to tell by yet: the event's title is
put on for now and looked at again once the voices are known, recheck()).
"""

import json
import re
from typing import Any, Dict, Iterable, List, Optional, Set

MESSENGERS = {"telegram", "whatsapp", "discord", "skype"}
_CAL_HEAD_RE = re.compile(r"^(?:Участники по календарю|Participants \(calendar\))\s*:.*(?:\n|$)", re.M)


def _keys(name: str) -> Set[str]:
    """The sound of each word of a name (Latin and Cyrillic alike); an e-mail gives the words before «@»."""
    from app.vocab import sound_key

    text = str(name or "")
    if "@" in text:
        text = text.split("@", 1)[0]
    words = [w for w in re.split(r"[^\w]+|_", text) if len(w) >= 3 and not w.isdigit()]
    return {k for k in (sound_key(w) for w in words) if len(k) >= 3}


def _my_keys() -> Set[str]:
    try:
        from app.people import my_names

        return set().union(*[_keys(n) for n in my_names()]) if my_names() else set()
    except Exception:
        return set()


def same_person(a: str, b: str, mine: Optional[Set[str]] = None) -> bool:
    """A word of the name (a first name or a surname, in any spelling) in both, not one of the user's own."""
    mine = _my_keys() if mine is None else mine
    return bool((_keys(a) & _keys(b)) - mine)


def _others(names: Iterable[str], mine: Set[str]) -> List[str]:
    from app.voice_profiles import is_default_name

    out: List[str] = []
    for n in names:
        n = str(n or "").strip()
        if n and not is_default_name(n) and n.lower() != "teams" and (_keys(n) - mine) and n not in out:
            out.append(n)
    return out


def _titles_alike(a: str, b: str) -> bool:
    ka, kb = _keys(a), _keys(b)
    if not ka or not kb:
        return False
    return len(ka & kb) / min(len(ka), len(kb)) >= 0.6


def verdict(ev: Dict[str, Any], title: str = "", names: Iterable[str] = (), call_app: str = "") -> str:
    from app.ollama_client import is_generic_title

    mine = _my_keys()
    invited = [a for a in ev.get("attendees") or [] if _keys(a) - mine]
    heard = _others(names, mine)
    if heard:
        if any(same_person(h, a, mine) for h in heard for a in invited):
            return "yes"
        if invited:
            return "no"  # the people of the conversation are known, and none of them was invited
    title = (title or "").strip()
    if title and not is_generic_title(title):
        if _titles_alike(title, ev.get("title") or ""):
            return "yes"
        if any(same_person(title, a, mine) for a in invited):
            # a call window named after one of the invitees: the meeting itself when it is a one-on-one
            return "yes" if len(invited) <= 1 else "unknown"
        return "no"  # another meeting (its Teams window) or a name the user gave it
    if (call_app or "").lower() in MESSENGERS and ev.get("online"):
        return "no"  # a meeting with a link is not held in a messenger call
    return "unknown"


def call_title(names: Iterable[str], lang: str = "ru") -> str:
    """«Звонок: Анна Смирнова, Борис» for a conversation that is not the calendar's meeting ("" without names)."""
    heard = _others(names, _my_keys())
    if not heard:
        return ""
    return ("Call: " if lang == "en" else "Звонок: ") + ", ".join(heard[:3]) + (" …" if len(heard) > 3 else "")


def _stored(m: Dict[str, Any]) -> Dict[str, Any]:
    try:
        v = json.loads(m.get("calendar_json") or "{}")
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


def recheck(meeting_id: int, speakers: Dict[str, Any]) -> str:
    """After the transcription, the voices known: a recording given the event's title «for now» keeps it only
    when the people heard are the invitees. Returns the verdict ("" when there was nothing to look at)."""
    from app.database import get_meeting, update_meeting_fields

    m = get_meeting(meeting_id) or {}
    cal = _stored(m)
    if not cal or cal.get("sure"):
        return ""
    names = [(s or {}).get("name") or "" for s in (speakers or {}).values()]
    v = verdict({"title": cal.get("title") or "", "attendees": cal.get("attendees") or [], "online": cal.get("online")},
                names=names, call_app=cal.get("call_app") or "")
    if v == "no":
        fields: Dict[str, Any] = {"calendar_json": json.dumps({**cal, "sure": True, "match": False}, ensure_ascii=False)}
        if (m.get("title") or "") == (cal.get("title") or "")[:300]:  # not renamed by the user meanwhile
            named = call_title(names, "en" if (m.get("language") or "") == "en" else "ru")
            fields.update(title=named or cal.get("recorded_title") or "Запись", title_is_default=0 if named else 1)
        notes = m.get("user_notes") or ""
        if _CAL_HEAD_RE.search(notes):
            fields["user_notes"] = _CAL_HEAD_RE.sub("", notes, count=1).strip()
        update_meeting_fields(meeting_id, **fields)
        print(f"[calendar] meeting {meeting_id}: the voices are not the invitees of «{cal.get('title')}», "
              f"named {fields.get('title', m.get('title'))!r}", flush=True)
    elif v == "yes":
        update_meeting_fields(meeting_id, calendar_json=json.dumps({**cal, "sure": True, "match": True}, ensure_ascii=False))
    return v
