"""The announcement buttons and playing them.

Buttons live in the app's state as a list of dicts:
``{"id", "title", "icon", "message", "speakers"}``, where ``speakers`` is
``None`` for "All speakers" or a list of media_player entity ids.
"""
import logging
import time
import uuid

from bdh_sdk.plugins import as_list
from bdh_sdk.settings import app_setting
from bdh_sdk.storage import app_state

log = logging.getLogger(__name__)

APP = "announcements"
KEY = "buttons"
VOICE = "AvaNeural"
MAX_BUTTONS = 20
MAX_TITLE = 40
MAX_MESSAGE = 300
ICONS = ("utensils", "car", "bed", "bullhorn", "person-walking",
         "gift", "phone", "book", "dog", "bell")
DEFAULT_ICON = "bullhorn"
KNOWN_TTL = 60  # seconds between speaker lookups for the homepage
NOT_SET_UP = "isn't set up"  # in the hub's error when it has no Home Assistant

_known = {"ids": None, "at": None}


def load():
    buttons = app_state(APP).get(KEY) or []
    return [b for b in buttons if isinstance(b, dict) and b.get("id")]


def save(buttons):
    app_state(APP).set(KEY, buttons)


def find(button_id):
    return next((b for b in load() if b["id"] == button_id), None)


def clean(post_title, post_icon, post_message, mode, picked):
    """Validated button fields from a form; raises ValueError."""
    title = " ".join(str(post_title or "").split())[:MAX_TITLE]
    message = " ".join(str(post_message or "").split())[:MAX_MESSAGE]
    if not title:
        raise ValueError("A button needs a name.")
    if not message:
        raise ValueError("A button needs something to say.")
    icon = post_icon if post_icon in ICONS else DEFAULT_ICON
    speakers = None
    if mode == "pick":
        speakers = list(dict.fromkeys(s for s in picked if s))
        if not speakers:
            raise ValueError("Pick at least one speaker, or play on all speakers.")
    return {"title": title, "icon": icon, "message": message, "speakers": speakers}


def add(fields):
    buttons = load()
    if len(buttons) >= MAX_BUTTONS:
        raise ValueError(f"You can have up to {MAX_BUTTONS} buttons.")
    button = {"id": uuid.uuid4().hex[:10], **fields}
    save(buttons + [button])
    return button


def update(button_id, fields):
    buttons = load()
    for b in buttons:
        if b["id"] == button_id:
            b.update(fields)
            save(buttons)
            return b
    raise KeyError(button_id)


def delete(button_id):
    save([b for b in load() if b["id"] != button_id])


def move(button_id, step):
    buttons = load()
    i = next((n for n, b in enumerate(buttons) if b["id"] == button_id), None)
    j = None if i is None else i + step
    if i is not None and 0 <= j < len(buttons):
        buttons[i], buttons[j] = buttons[j], buttons[i]
        save(buttons)


def all_speakers():
    raw = app_setting(APP, "speakers", None)
    return as_list(raw) if raw else []


def volume():
    try:
        return max(0, min(100, int(app_setting(APP, "volume", 50))))
    except (TypeError, ValueError):
        return 50


def chime():
    value = app_setting(APP, "chime", "westminster")
    return None if value in (None, "", "none") else value


def forget_speakers():
    _known.update(ids=None, at=None)


def known_speakers():
    """Ids of the speakers Home Assistant has, or None when it has none to give.

    Looked up at most every ``KNOWN_TTL`` seconds. When Home Assistant is
    unreachable the last list is kept, so a blip doesn't hide the buttons;
    when the hub has no Home Assistant set up there are no speakers at all.
    """
    from bdh_sdk import speakers as sp

    now = time.monotonic()
    if _known["at"] is not None and now - _known["at"] < KNOWN_TTL:
        return _known["ids"]
    try:
        ids = frozenset(sid for sid, _name in sp.list_speakers())
    except Exception as exc:
        log.warning("couldn't list speakers: %s", exc)
        ids = None if NOT_SET_UP in str(exc) else _known["ids"]
    _known.update(ids=ids, at=now)
    return ids


def targets(button):
    return button.get("speakers") or all_speakers()


def playable(button):
    """Whether at least one of the button's speakers exists in Home Assistant."""
    known = known_speakers()
    return bool(known) and any(s in known for s in targets(button))


def play(button):
    """Announce ``button``; returns a short result for the user."""
    from bdh_sdk import speakers as sp

    speakers = targets(button)
    if not speakers:
        raise sp.AnnounceError('No speakers set up. Pick them under Settings › Announcements.')
    failed = sp.announce(button["message"], speakers, volume=volume(), chime=chime(), voice=VOICE)
    played = len(speakers) - len(failed)
    noun = "speaker" if played == 1 else "speakers"
    if failed:
        return f"Announced on {played} {noun}, {len(failed)} didn't respond"
    return f"Announced on {played} {noun}"
