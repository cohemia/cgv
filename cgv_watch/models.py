"""CGV 상영회차(Showtime) 모델."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlencode

BASE_URL = "http://www.cgv.co.kr"


@dataclass(frozen=True)
class Showtime:
    """상영시간표 한 칸(= 예매 가능한 회차 하나)."""

    theater_code: str
    play_ymd: str  # YYYYMMDD
    screen_code: str
    play_num: str
    start_time: str  # HHMM
    seat_remain: int
    movie_idx: str = ""
    movie_name: str = ""
    theater_name: str = ""
    screen_name: str = ""
    end_time: str = ""
    seat_capacity: int = 0
    movie_group_cd: str = ""
    raw: dict = field(default_factory=dict, repr=False, compare=False)

    @property
    def key(self) -> str:
        """회차를 유일하게 구분하는 키."""
        return f"{self.theater_code}:{self.play_ymd}:{self.screen_code}:{self.play_num}"

    @property
    def start_dt(self) -> datetime:
        """상영 시작 시각. 파싱 실패 시 그 날 자정으로 떨어진다."""
        hhmm = (self.start_time or "0000").zfill(4)[:4]
        try:
            return datetime.strptime(f"{self.play_ymd}{hhmm}", "%Y%m%d%H%M")
        except ValueError:
            return datetime.strptime(self.play_ymd, "%Y%m%d")

    @property
    def start_hhmm(self) -> str:
        s = (self.start_time or "").zfill(4)[:4]
        return f"{s[:2]}:{s[2:]}" if len(s) == 4 else "??:??"

    @property
    def end_hhmm(self) -> str:
        s = (self.end_time or "").zfill(4)[:4]
        return f"{s[:2]}:{s[2:]}" if len(s) == 4 else ""

    def booking_url(self) -> str:
        """예매 페이지 딥링크.

        CGV 예매 페이지는 쿼리스트링으로 극장/일자/상영관/회차를 받는다.
        사이트 개편으로 파라미터가 바뀌면 config 의 booking.url_template 로 덮어쓸 수 있다.
        """
        params = {
            "MOVIE_CD": self.movie_idx,
            "MOVIE_CD_GROUP": self.movie_group_cd or self.movie_idx,
            "THEATER_CD": self.theater_code,
            "SCREEN_CD": self.screen_code,
            "PLAY_YMD": self.play_ymd,
            "PLAY_NUM": self.play_num,
        }
        return f"{BASE_URL}/ticket/?{urlencode({k: v for k, v in params.items() if v})}"

    def describe(self) -> str:
        bits = [self.movie_name or f"movie#{self.movie_idx}"]
        if self.theater_name:
            bits.append(self.theater_name)
        if self.screen_name:
            bits.append(self.screen_name)
        when = f"{self.play_ymd[4:6]}/{self.play_ymd[6:8]} {self.start_hhmm}"
        if self.end_hhmm:
            when += f"~{self.end_hhmm}"
        bits.append(when)
        seats = f"{self.seat_remain}석"
        if self.seat_capacity:
            seats += f"/{self.seat_capacity}"
        bits.append(seats)
        return " | ".join(bits)
