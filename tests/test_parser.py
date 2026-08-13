"""파서·필터·감시 로직 테스트.

주의: 픽스처는 실제 CGV 응답이 아니라 합성 HTML이다. 이 테스트가 통과한다고
실제 사이트에서 동작한다는 뜻은 아니고, 리팩터링 시 로직이 깨지지 않게 잡아주는 용도다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cgv_watch.client import filter_showtimes, parse_showtimes
from cgv_watch.config import Target, resolve_dates
from cgv_watch.models import Showtime

FIXTURE = Path(__file__).parent / "fixtures" / "showtimes_sample.html"


@pytest.fixture(scope="module")
def showtimes():
    return parse_showtimes(FIXTURE.read_text(encoding="utf-8"), "0013", "20260820")


def test_parses_all_showtimes(showtimes):
    assert len(showtimes) == 3


def test_sorted_by_start_time(showtimes):
    assert [s.start_time for s in showtimes] == ["1030", "1900", "2230"]


def test_extracts_data_attributes(showtimes):
    late = next(s for s in showtimes if s.play_num == "4")
    assert late.seat_remain == 12
    assert late.movie_name == "아바타: 불과 재"
    assert late.screen_code == "0001"
    assert late.movie_idx == "88413"
    assert late.key == "0013:20260820:0001:4"


def test_screen_name_and_capacity_from_info_hall(showtimes):
    imax = next(s for s in showtimes if s.play_num == "3")
    assert "IMAX" in imax.screen_name
    assert imax.seat_capacity == 620


def test_soldout_showtime_has_zero_remaining(showtimes):
    soldout = next(s for s in showtimes if s.play_num == "3")
    assert soldout.seat_remain == 0


def test_booking_url_contains_identifiers(showtimes):
    url = showtimes[0].booking_url()
    assert "THEATER_CD=0013" in url
    assert "PLAY_YMD=20260820" in url
    assert "PLAY_NUM=1" in url


def test_filter_by_movie_and_screen(showtimes):
    got = filter_showtimes(showtimes, movie_contains="아바타", screen_contains="IMAX")
    assert {s.play_num for s in got} == {"3", "4"}


def test_filter_by_time_window(showtimes):
    got = filter_showtimes(showtimes, time_from="18:00", time_to="23:59")
    assert {s.play_num for s in got} == {"3", "4"}


def test_filter_empty_criteria_keeps_everything(showtimes):
    assert len(filter_showtimes(showtimes)) == 3


def test_parse_empty_html_returns_nothing():
    assert parse_showtimes("<html><body>휴관일</body></html>", "0013", "20260820") == []


def test_resolve_dates_accepts_mixed_formats():
    assert resolve_dates("2026-08-20") == ["20260820"]
    assert resolve_dates("20260820") == ["20260820"]
    assert len(resolve_dates([{"from": "2026-08-20", "days": 3}])) == 3
    assert resolve_dates(["2026-08-20", "20260820"]) == ["20260820"]  # 중복 제거


def test_target_defaults():
    t = Target.from_dict({"theater_code": "0013", "dates": "2026-08-20"})
    assert t.min_seats == 1 and t.auto_book is True


# ------------------------------------------------------------------ 감시 로직


def _st(remain: int, play_num: str = "1") -> Showtime:
    return Showtime(
        theater_code="0013",
        play_ymd="20990101",  # 항상 미래 (지난 회차 스킵 로직 회피)
        screen_code="0001",
        play_num=play_num,
        start_time="1900",
        seat_remain=remain,
    )


def _watcher(min_seats: int = 2):
    from cgv_watch.config import BookingConfig, Config, PollConfig
    from cgv_watch.watcher import Watcher

    cfg = Config(
        poll=PollConfig(),
        booking=BookingConfig(enabled=False),
        notify={},
        targets=[Target.from_dict({"theater_code": "0013", "min_seats": min_seats})],
        state_file="",
    )
    return Watcher(cfg), cfg.targets[0]


def test_alerts_only_on_transition_to_available():
    w, target = _watcher(min_seats=2)
    assert w._handle(_st(0), target) is False   # 매진
    assert w._handle(_st(3), target) is True    # 취소표 발생 → 알림
    assert w._handle(_st(3), target) is False   # 계속 열려 있음 → 재알림 안 함


def test_alerts_again_after_selling_out_and_reopening():
    w, target = _watcher(min_seats=2)
    w._handle(_st(0), target)
    w._handle(_st(5), target)
    w._handle(_st(0), target)                   # 다시 매진
    w.last_alert.clear()                        # 쿨다운 해제
    assert w._handle(_st(5), target) is True    # 또 나오면 다시 알림


def test_respects_min_seats():
    w, target = _watcher(min_seats=2)
    assert w._handle(_st(0), target) is False
    assert w._handle(_st(1), target) is False   # 1석뿐이라 2명은 못 봄
    assert w._handle(_st(2), target) is True


def test_cooldown_suppresses_repeat_alert():
    w, target = _watcher(min_seats=1)
    assert w._handle(_st(1), target) is True
    w.was_available.clear()                     # 매진→가능 전이를 인위적으로 재현
    assert w._handle(_st(1), target) is False   # 쿨다운 중이라 억제
