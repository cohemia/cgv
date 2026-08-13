"""설정 로딩. YAML + ${ENV_VAR} 치환 + .env 파일 지원 (외부 의존성 없음)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import yaml

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


class ConfigError(ValueError):
    pass


def load_dotenv(path: str | Path = ".env") -> None:
    """아주 단순한 .env 로더. 이미 설정된 환경변수는 덮어쓰지 않는다."""
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _expand(value):
    if isinstance(value, str):
        def sub(m: re.Match) -> str:
            return os.environ.get(m.group(1), m.group(2) or "")

        return _ENV_RE.sub(sub, value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


def resolve_dates(spec) -> list[str]:
    """날짜 지정을 YYYYMMDD 리스트로 바꾼다.

    허용: "2026-08-20", "20260820", "today", "tomorrow", "+3"(3일 뒤),
          {"from": "today", "days": 7}
    """
    today = date.today()

    def one(item) -> list[str]:
        if isinstance(item, date):
            return [item.strftime("%Y%m%d")]
        if isinstance(item, dict):
            start = one(item.get("from", "today"))[0]
            days = int(item.get("days", 1))
            base = date(int(start[:4]), int(start[4:6]), int(start[6:8]))
            return [(base + timedelta(days=i)).strftime("%Y%m%d") for i in range(max(days, 1))]
        text = str(item).strip().lower()
        if text in ("today", "오늘"):
            return [today.strftime("%Y%m%d")]
        if text in ("tomorrow", "내일"):
            return [(today + timedelta(days=1)).strftime("%Y%m%d")]
        if re.fullmatch(r"[+-]\d+", text):
            return [(today + timedelta(days=int(text))).strftime("%Y%m%d")]
        digits = re.sub(r"\D", "", text)
        if len(digits) == 8:
            return [digits]
        raise ConfigError(f"날짜 형식을 이해할 수 없습니다: {item!r}")

    items = spec if isinstance(spec, list) else [spec]
    out: list[str] = []
    for item in items:
        for d in one(item):
            if d not in out:
                out.append(d)
    return out


@dataclass
class Target:
    name: str
    theater_code: str
    dates: list[str]  # YYYYMMDD
    theater_name: str = ""
    movie_contains: str = ""
    movie_idx: str = ""
    screen_contains: str = ""
    time_from: str = ""
    time_to: str = ""
    min_seats: int = 1
    cooldown_minutes: int = 10
    auto_book: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> "Target":
        if not data.get("theater_code"):
            raise ConfigError(f"target '{data.get('name', '?')}' 에 theater_code 가 없습니다.")
        dates = resolve_dates(data.get("dates") or data.get("date") or "today")
        return cls(
            name=str(data.get("name") or data["theater_code"]),
            theater_code=str(data["theater_code"]).strip(),
            theater_name=str(data.get("theater_name", "")),
            dates=dates,
            movie_contains=str(data.get("movie_contains", "")),
            movie_idx=str(data.get("movie_idx", "")),
            screen_contains=str(data.get("screen_contains", "")),
            time_from=str(data.get("time_from", "")),
            time_to=str(data.get("time_to", "")),
            min_seats=int(data.get("min_seats", 1)),
            cooldown_minutes=int(data.get("cooldown_minutes", 10)),
            auto_book=bool(data.get("auto_book", True)),
        )


@dataclass
class PollConfig:
    interval_seconds: float = 30.0
    jitter_seconds: float = 10.0
    error_backoff_seconds: float = 60.0
    max_error_backoff_seconds: float = 600.0
    request_timeout: float = 10.0
    stop_when_done: bool = False


@dataclass
class BookingConfig:
    enabled: bool = False
    mode: str = "seat_select"  # off | open_only | seat_select
    seat_count: int = 1
    prefer_adjacent: bool = True
    user_data_dir: str = ".playwright/cgv-profile"
    headless: bool = False
    step_timeout_seconds: float = 20.0
    screenshot_dir: str = "screenshots"
    url_template: str = ""
    selectors: dict = field(default_factory=dict)


@dataclass
class Config:
    poll: PollConfig
    booking: BookingConfig
    notify: dict
    targets: list[Target]
    state_file: str = "state.json"

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        p = Path(path)
        if not p.is_file():
            raise ConfigError(
                f"설정 파일이 없습니다: {p}\nconfig.example.yaml 을 config.yaml 로 복사해서 채우세요."
            )
        raw = _expand(yaml.safe_load(p.read_text(encoding="utf-8")) or {})
        targets = [Target.from_dict(t) for t in (raw.get("targets") or [])]
        if not targets:
            raise ConfigError("targets 가 비어 있습니다. 감시할 극장/영화를 최소 하나 넣어주세요.")
        return cls(
            poll=PollConfig(**(raw.get("poll") or {})),
            booking=BookingConfig(**(raw.get("booking") or {})),
            notify=raw.get("notify") or {},
            targets=targets,
            state_file=str(raw.get("state_file", "state.json")),
        )
