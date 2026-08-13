"""CGV 상영시간표 조회 클라이언트.

CGV 웹의 상영시간표 iframe(`/common/showtimes/iframeTheater.aspx`)은 회차마다
`data-seatremaincnt`(잔여좌석) 같은 data-* 속성을 달고 내려온다. 로그인 없이 읽을 수
있어서 "빈자리 감시"의 폴링 대상으로 가장 싸다.

주의: CGV 는 예고 없이 마크업을 바꾼다. 파서는 특정 클래스 구조에 의존하지 않고
`data-seatremaincnt` 를 가진 앵커를 전부 긁은 뒤 주변에서 부가정보를 보강하는 식으로
동작한다. 그래도 깨지면 `python -m cgv_watch dump` 로 원본 HTML을 떠서 확인하면 된다.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable

import requests
from bs4 import BeautifulSoup, Tag

from .models import BASE_URL, Showtime

log = logging.getLogger(__name__)

SHOWTIME_URL = f"{BASE_URL}/common/showtimes/iframeTheater.aspx"
THEATER_LIST_URL = f"{BASE_URL}/theaters/"

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_CAPACITY_RE = re.compile(r"총\s*([\d,]+)\s*석")
_DIGITS_RE = re.compile(r"-?\d+")


class CgvError(RuntimeError):
    pass


def _to_int(value: object, default: int = 0) -> int:
    if value is None:
        return default
    m = _DIGITS_RE.search(str(value).replace(",", ""))
    return int(m.group()) if m else default


def _first_attr(attrs: dict, *names: str, default: str = "") -> str:
    for name in names:
        v = attrs.get(name)
        if v not in (None, ""):
            return str(v).strip()
    return default


def _ancestor_text(node: Tag, selector: str, limit: int = 6) -> str:
    """앵커에서 위로 올라가며 selector 에 맞는 요소의 텍스트를 찾는다."""
    cur: Tag | None = node
    for _ in range(limit):
        cur = cur.parent if cur is not None else None
        if not isinstance(cur, Tag):
            break
        found = cur.select_one(selector)
        if found:
            text = found.get_text(" ", strip=True)
            if text:
                return text
    return ""


def _hall_info(node: Tag) -> tuple[str, int]:
    """상영관 이름과 총 좌석수를 앵커 주변에서 추출한다."""
    cur: Tag | None = node
    for _ in range(6):
        cur = cur.parent if cur is not None else None
        if not isinstance(cur, Tag):
            break
        hall = cur.select_one(".info-hall")
        if not hall:
            continue
        items = [li.get_text(" ", strip=True) for li in hall.select("li")]
        text = " ".join(items) or hall.get_text(" ", strip=True)
        cap_match = _CAPACITY_RE.search(text)
        capacity = _to_int(cap_match.group(1)) if cap_match else 0
        # "총 100석" 항목을 뺀 나머지를 상영관 이름으로 본다 (예: "2D", "6관").
        name_bits = [i for i in items if not _CAPACITY_RE.search(i)]
        return (" ".join(name_bits).strip(), capacity)
    return ("", 0)


def parse_showtimes(html: str, theater_code: str = "", play_ymd: str = "") -> list[Showtime]:
    """상영시간표 HTML에서 회차 목록을 뽑는다."""
    soup = BeautifulSoup(html, "lxml")
    anchors = soup.select("[data-seatremaincnt]")
    if not anchors:
        # 속성명이 바뀐 경우를 대비한 느슨한 폴백.
        anchors = [
            t
            for t in soup.find_all(True)
            if any(k.startswith("data-") and "seatremain" in k.lower() for k in t.attrs)
        ]

    showtimes: list[Showtime] = []
    for a in anchors:
        attrs = {k.lower(): v for k, v in a.attrs.items()}
        remain_key = next(
            (k for k in attrs if "seatremain" in k), "data-seatremaincnt"
        )
        screen_name, capacity = _hall_info(a)
        movie_name = (
            _first_attr(attrs, "data-moviename", "data-title")
            or _ancestor_text(a, ".info-movie strong")
            or _ancestor_text(a, ".info-movie")
        )
        st = Showtime(
            theater_code=_first_attr(attrs, "data-theatercode", default=theater_code),
            play_ymd=_first_attr(attrs, "data-playymd", default=play_ymd),
            screen_code=_first_attr(attrs, "data-screencode"),
            play_num=_first_attr(attrs, "data-playnum"),
            start_time=_first_attr(attrs, "data-playstarttime", "data-starttime"),
            end_time=_first_attr(attrs, "data-playendtime", "data-endtime"),
            seat_remain=_to_int(attrs.get(remain_key), default=0),
            seat_capacity=_to_int(attrs.get("data-seatcapacity"), default=capacity),
            movie_idx=_first_attr(attrs, "data-movieidx", "data-moviecd"),
            movie_group_cd=_first_attr(attrs, "data-moviecdgroup", "data-moviegroupcd"),
            movie_name=movie_name,
            screen_name=_first_attr(attrs, "data-screenname", default=screen_name),
            raw=dict(attrs),
        )
        if not st.play_num or not st.screen_code:
            log.debug("회차 식별자가 없어 건너뜀: %s", attrs)
            continue
        showtimes.append(st)

    showtimes.sort(key=lambda s: (s.play_ymd, s.start_time))
    return showtimes


class CgvClient:
    def __init__(
        self,
        timeout: float = 10.0,
        user_agent: str = DEFAULT_UA,
        session: requests.Session | None = None,
    ) -> None:
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
                "Referer": f"{BASE_URL}/theaters/",
            }
        )

    def fetch_showtimes_html(self, theater_code: str, play_ymd: str) -> str:
        params = {"theatercode": theater_code, "date": play_ymd}
        try:
            res = self.session.get(SHOWTIME_URL, params=params, timeout=self.timeout)
            res.raise_for_status()
        except requests.RequestException as exc:  # 네트워크/HTTP 오류는 호출부에서 백오프
            raise CgvError(f"상영시간표 조회 실패 ({theater_code}/{play_ymd}): {exc}") from exc
        res.encoding = res.encoding or "utf-8"
        return res.text

    def get_showtimes(self, theater_code: str, play_ymd: str) -> list[Showtime]:
        html = self.fetch_showtimes_html(theater_code, play_ymd)
        showtimes = parse_showtimes(html, theater_code=theater_code, play_ymd=play_ymd)
        if not showtimes:
            log.warning(
                "회차를 하나도 못 읽었습니다 (%s/%s). 휴관일이거나 마크업이 바뀐 것일 수 있어요. "
                "`python -m cgv_watch dump --theater %s --date %s` 로 원본을 확인하세요.",
                theater_code,
                play_ymd,
                theater_code,
                play_ymd,
            )
        return showtimes

    def get_theaters(self) -> list[tuple[str, str]]:
        """극장 코드 목록. (코드, 이름) 튜플."""
        try:
            res = self.session.get(THEATER_LIST_URL, timeout=self.timeout)
            res.raise_for_status()
        except requests.RequestException as exc:
            raise CgvError(f"극장 목록 조회 실패: {exc}") from exc

        soup = BeautifulSoup(res.text, "lxml")
        found: dict[str, str] = {}
        for a in soup.find_all("a"):
            href = a.get("href") or ""
            code = ""
            m = re.search(r"[?&]theaterCode=([0-9A-Za-z]+)", href, re.IGNORECASE)
            if m:
                code = m.group(1)
            else:
                for k, v in a.attrs.items():
                    if k.lower() in ("data-theatercode", "theatercode") and v:
                        code = str(v)
                        break
            name = a.get_text(" ", strip=True)
            if code and name:
                found.setdefault(code, name)
        return sorted(found.items())


def filter_showtimes(
    showtimes: Iterable[Showtime],
    movie_contains: str = "",
    movie_idx: str = "",
    screen_contains: str = "",
    time_from: str = "",
    time_to: str = "",
) -> list[Showtime]:
    """설정된 조건으로 회차를 좁힌다. time_from/time_to 는 "HH:MM"."""

    def hhmm_to_int(value: str) -> int:
        return _to_int(value.replace(":", ""), default=0)

    lo = hhmm_to_int(time_from) if time_from else -1
    hi = hhmm_to_int(time_to) if time_to else 9999

    out = []
    for s in showtimes:
        if movie_idx and s.movie_idx != movie_idx:
            continue
        if movie_contains and movie_contains.lower() not in (s.movie_name or "").lower():
            continue
        if screen_contains and screen_contains.lower() not in (s.screen_name or "").lower():
            continue
        start = _to_int(s.start_time, default=0)
        if not (lo <= start <= hi):
            continue
        out.append(s)
    return out
