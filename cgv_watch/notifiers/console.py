from __future__ import annotations

import logging

log = logging.getLogger("cgv_watch.notify")


class ConsoleNotifier:
    name = "console"

    def send(self, title: str, body: str, url: str = "") -> None:
        line = f"\n{'=' * 60}\n[{title}]\n{body}"
        if url:
            line += f"\n{url}"
        line += f"\n{'=' * 60}"
        log.info(line)
        # 터미널을 보고 있지 않아도 알아채도록 벨 문자를 울린다.
        print("\a", end="", flush=True)
