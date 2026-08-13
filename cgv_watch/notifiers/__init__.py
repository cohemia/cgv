"""알림 채널. 어떤 채널이 실패해도 감시 루프는 멈추지 않는다."""

from __future__ import annotations

import logging
from typing import Protocol

log = logging.getLogger(__name__)


class Notifier(Protocol):
    name: str

    def send(self, title: str, body: str, url: str = "") -> None: ...


class NotifierGroup:
    def __init__(self, notifiers: list[Notifier]) -> None:
        self.notifiers = notifiers

    def send(self, title: str, body: str, url: str = "") -> None:
        for n in self.notifiers:
            try:
                n.send(title, body, url)
            except Exception:  # 알림 실패가 감시를 죽이면 안 된다
                log.exception("알림 전송 실패: %s", getattr(n, "name", n))

    def __bool__(self) -> bool:
        return bool(self.notifiers)


def build_notifiers(cfg: dict) -> NotifierGroup:
    from .console import ConsoleNotifier
    from .desktop import DesktopNotifier
    from .telegram import TelegramNotifier

    notifiers: list[Notifier] = []
    cfg = cfg or {}

    tg = cfg.get("telegram") or {}
    if tg.get("enabled"):
        token, chat_id = tg.get("bot_token", ""), tg.get("chat_id", "")
        if token and chat_id:
            notifiers.append(TelegramNotifier(token, str(chat_id)))
        else:
            log.warning(
                "telegram 알림이 켜져 있지만 bot_token/chat_id 가 비었습니다. "
                ".env 의 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 를 확인하세요."
            )

    if (cfg.get("desktop") or {}).get("enabled"):
        notifiers.append(DesktopNotifier(sound=(cfg.get("desktop") or {}).get("sound", True)))

    if (cfg.get("console") or {}).get("enabled", True):
        notifiers.append(ConsoleNotifier())

    return NotifierGroup(notifiers)
