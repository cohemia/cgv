"""OS 기본 알림 도구를 subprocess 로 호출한다 (추가 패키지 없음).

macOS  : osascript + afplay
Linux  : notify-send + paplay/aplay
Windows: PowerShell 토스트(BurntToast 없이 WinRT API 직접 호출)
"""

from __future__ import annotations

import platform
import shutil
import subprocess


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=False, capture_output=True, timeout=15)


class DesktopNotifier:
    name = "desktop"

    def __init__(self, sound: bool = True) -> None:
        self.sound = sound
        self.system = platform.system()

    def send(self, title: str, body: str, url: str = "") -> None:
        text = f"{body}\n{url}".strip()
        if self.system == "Darwin":
            self._macos(title, text)
        elif self.system == "Windows":
            self._windows(title, text)
        else:
            self._linux(title, text)

    def _macos(self, title: str, text: str) -> None:
        safe = text.replace('"', "'").replace("\n", " ")
        sound = ' sound name "Glass"' if self.sound else ""
        _run(["osascript", "-e", f'display notification "{safe}" with title "{title}"{sound}'])
        if self.sound and shutil.which("afplay"):
            _run(["afplay", "/System/Library/Sounds/Glass.aiff"])

    def _linux(self, title: str, text: str) -> None:
        if shutil.which("notify-send"):
            _run(["notify-send", "-u", "critical", title, text])
        if self.sound:
            for player, path in (
                ("paplay", "/usr/share/sounds/freedesktop/stereo/complete.oga"),
                ("aplay", "/usr/share/sounds/alsa/Front_Center.wav"),
            ):
                if shutil.which(player):
                    _run([player, path])
                    break

    def _windows(self, title: str, text: str) -> None:
        safe_title = title.replace("'", "''")
        safe_text = text.replace("'", "''")
        script = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications,"
            " ContentType=WindowsRuntime] > $null;"
            # 5 = ToastText02 (굵은 제목 1줄 + 본문 1줄)
            "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(5);"
            f"$t.GetElementsByTagName('text')[0].AppendChild($t.CreateTextNode('{safe_title}')) > $null;"
            f"$t.GetElementsByTagName('text')[1].AppendChild($t.CreateTextNode('{safe_text}')) > $null;"
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('CGV Watch')"
            ".Show([Windows.UI.Notifications.ToastNotification]::new($t));"
        )
        if self.sound:
            script += "[console]::beep(880,400);[console]::beep(1320,400);"
        _run(["powershell", "-NoProfile", "-Command", script])
