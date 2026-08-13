"""폴링 루프: 잔여좌석을 감시하다가 조건을 만족하면 알림 + (옵션) 자동 예매."""

from __future__ import annotations

import json
import logging
import random
import threading
import time
from datetime import datetime
from pathlib import Path

from .client import CgvClient, CgvError, filter_showtimes
from .config import Config, Target
from .models import Showtime
from .notifiers import NotifierGroup

log = logging.getLogger(__name__)


class Watcher:
    def __init__(
        self,
        config: Config,
        client: CgvClient | None = None,
        notifier: NotifierGroup | None = None,
        booker=None,
    ) -> None:
        self.config = config
        self.client = client or CgvClient(timeout=config.poll.request_timeout)
        self.notifier = notifier or NotifierGroup([])
        self.booker = booker
        # 회차 키 -> 직전 폴링에서 "예매 가능"이었는지. 가능→가능 반복 알림을 막는다.
        self.was_available: dict[str, bool] = {}
        # 회차 키 -> 마지막 알림 시각(쿨다운용)
        self.last_alert: dict[str, float] = {}
        self._booking_lock = threading.Lock()
        self._booking_thread: threading.Thread | None = None
        self._state_path = Path(config.state_file) if config.state_file else None
        self._load_state()

    # ---------------------------------------------------------------- state
    def _load_state(self) -> None:
        if not self._state_path or not self._state_path.is_file():
            return
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            self.was_available = dict(data.get("was_available", {}))
            self.last_alert = {k: float(v) for k, v in (data.get("last_alert") or {}).items()}
            log.debug("이전 상태를 %s 에서 복원했습니다.", self._state_path)
        except (OSError, ValueError):
            log.warning("상태 파일을 읽지 못해 새로 시작합니다: %s", self._state_path)

    def _save_state(self) -> None:
        if not self._state_path:
            return
        try:
            self._state_path.write_text(
                json.dumps(
                    {"was_available": self.was_available, "last_alert": self.last_alert},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            log.debug("상태 저장 실패(무시): %s", exc)

    # ----------------------------------------------------------------- loop
    def run(self, once: bool = False) -> None:
        poll = self.config.poll
        backoff = 0.0
        targets = [t for t in self.config.targets]
        self._announce_start(targets)

        while True:
            had_error = False
            hits = 0
            for target in targets:
                try:
                    hits += self._check_target(target)
                except CgvError as exc:
                    had_error = True
                    log.warning("%s", exc)
                except Exception:
                    had_error = True
                    log.exception("target '%s' 처리 중 예기치 못한 오류", target.name)

            self._save_state()

            if once:
                return
            if hits and poll.stop_when_done:
                log.info("stop_when_done=true 라서 감시를 종료합니다.")
                self._join_booking()
                return

            if had_error:
                backoff = min(
                    poll.max_error_backoff_seconds,
                    backoff * 2 if backoff else poll.error_backoff_seconds,
                )
                sleep_for = backoff
                log.info("오류 발생 → %.0f초 후 재시도", sleep_for)
            else:
                backoff = 0.0
                sleep_for = poll.interval_seconds + random.uniform(0, poll.jitter_seconds)

            try:
                time.sleep(sleep_for)
            except KeyboardInterrupt:
                log.info("중단됨.")
                self._join_booking()
                return

    def _announce_start(self, targets: list[Target]) -> None:
        for t in targets:
            log.info(
                "감시 시작: %s (극장 %s, 날짜 %s, 영화 '%s', 상영관 '%s', %s~%s, %d석 이상)",
                t.name,
                t.theater_code,
                ",".join(t.dates),
                t.movie_contains or "전체",
                t.screen_contains or "전체",
                t.time_from or "00:00",
                t.time_to or "23:59",
                t.min_seats,
            )

    # -------------------------------------------------------------- checking
    def _check_target(self, target: Target) -> int:
        hits = 0
        now = datetime.now()
        for play_ymd in target.dates:
            showtimes = self.client.get_showtimes(target.theater_code, play_ymd)
            matched = filter_showtimes(
                showtimes,
                movie_contains=target.movie_contains,
                movie_idx=target.movie_idx,
                screen_contains=target.screen_contains,
                time_from=target.time_from,
                time_to=target.time_to,
            )
            log.debug(
                "[%s/%s] 전체 %d회차 중 조건 일치 %d회차",
                target.theater_code,
                play_ymd,
                len(showtimes),
                len(matched),
            )
            for st in matched:
                if st.start_dt < now:
                    continue  # 이미 시작한 회차
                if target.theater_name and not st.theater_name:
                    st = _with_theater_name(st, target.theater_name)
                if self._handle(st, target):
                    hits += 1
        return hits

    def _handle(self, st: Showtime, target: Target) -> bool:
        available = st.seat_remain >= target.min_seats
        previously = self.was_available.get(st.key, False)
        self.was_available[st.key] = available

        if not available:
            return False
        if previously:
            return False  # 이미 열려 있던 회차 — 새로 난 빈자리가 아니다

        last = self.last_alert.get(st.key, 0.0)
        if time.time() - last < target.cooldown_minutes * 60:
            log.debug("쿨다운 중이라 알림 생략: %s", st.key)
            return False
        self.last_alert[st.key] = time.time()

        url = st.booking_url()
        log.info("🎟️  빈자리 발견: %s", st.describe())
        self.notifier.send(
            title=f"🎟️ CGV 빈자리 {st.seat_remain}석",
            body=f"{st.describe()}\n(감시: {target.name})",
            url=url,
        )

        if target.auto_book and self.booker is not None:
            self._start_booking(st)
        return True

    # -------------------------------------------------------------- booking
    def _start_booking(self, st: Showtime) -> None:
        """예매는 별도 스레드에서. 브라우저가 뜨는 동안에도 감시는 계속 돈다."""
        if not self._booking_lock.acquire(blocking=False):
            log.info("이미 다른 회차를 예매 중이라 이번 건은 알림만 보냅니다.")
            return

        def job() -> None:
            try:
                self.booker.book(st, notifier=self.notifier)
            except Exception:
                log.exception("자동 예매 실패 — 알림의 링크로 직접 예매하세요.")
                self.notifier.send(
                    title="⚠️ 자동 예매 실패",
                    body=f"{st.describe()}\n브라우저 자동화가 중간에 막혔습니다. 링크로 직접 진행하세요.",
                    url=st.booking_url(),
                )
            finally:
                self._booking_lock.release()

        self._booking_thread = threading.Thread(target=job, name="booker", daemon=True)
        self._booking_thread.start()

    def _join_booking(self, timeout: float = 300.0) -> None:
        if self._booking_thread and self._booking_thread.is_alive():
            log.info("예매 진행 중 — 브라우저 창을 확인하세요. (최대 %.0f초 대기)", timeout)
            self._booking_thread.join(timeout)


def _with_theater_name(st: Showtime, name: str) -> Showtime:
    from dataclasses import replace

    return replace(st, theater_name=name)
