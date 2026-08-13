"""텔레그램 봇 알림.

준비:
  1. 텔레그램에서 @BotFather 에게 /newbot → 토큰 받기
  2. 만든 봇과 대화를 한 번 시작(아무 메시지)
  3. https://api.telegram.org/bot<토큰>/getUpdates 를 열어 chat.id 확인
  4. .env 에 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 저장
"""

from __future__ import annotations

import json

import requests


class TelegramNotifier:
    name = "telegram"

    def __init__(self, bot_token: str, chat_id: str, timeout: float = 10.0) -> None:
        self.api = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self.chat_id = chat_id
        self.timeout = timeout

    def send(self, title: str, body: str, url: str = "") -> None:
        payload = {
            "chat_id": self.chat_id,
            "text": f"*{_escape(title)}*\n{_escape(body)}",
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True,
        }
        if url:
            payload["reply_markup"] = json.dumps(
                {"inline_keyboard": [[{"text": "🎬 예매 페이지 열기", "url": url}]]}
            )
        res = requests.post(self.api, data=payload, timeout=self.timeout)
        if not res.ok:
            raise RuntimeError(f"telegram {res.status_code}: {res.text[:300]}")


_SPECIALS = r"_*[]()~`>#+-=|{}.!"


def _escape(text: str) -> str:
    """MarkdownV2 예약문자 이스케이프."""
    return "".join("\\" + c if c in _SPECIALS else c for c in text)
