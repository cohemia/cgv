"""Playwright 로 예매 페이지를 열고 좌석까지 자동 선택한다. **결제는 하지 않는다.**

설계 원칙
---------
1. 결제 버튼은 절대 누르지 않는다. 마지막에 사람이 확인하고 누른다.
2. 어느 단계에서 막히든 브라우저를 그대로 열어둔다. 자동화가 실패해도
   사람이 이어서 진행하면 되므로, "실패 = 창을 닫는다"가 되면 안 된다.
3. 모든 셀렉터는 config 에서 덮어쓸 수 있다. CGV 는 마크업을 자주 바꾸고,
   이 기본값들은 확정된 값이 아니라 시작점이다. (README 의 "셀렉터 맞추기" 참고)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import BookingConfig
from .models import Showtime

log = logging.getLogger(__name__)

LOGIN_URL = "http://www.cgv.co.kr/user/login/"

# 기본 셀렉터 후보. 앞에서부터 순서대로 시도해 처음 보이는 것을 쓴다.
DEFAULT_SELECTORS: dict[str, list[str]] = {
    # 인원 선택 - 성인 수 늘리기
    "adult_plus": [
        "#personCountAdult .btn-plus",
        ".ticket-people .adult .btn-plus",
        "a[title='성인 인원 추가']",
        "button:has-text('성인') >> xpath=following::a[1]",
    ],
    # 좌석 하나하나
    "seat": [
        "a.seat:not(.unable):not(.disabled):not(.reserved)",
        "div.seat > a:not(.unable)",
        "[class*='seat'][data-seatno]:not([class*='unable'])",
        "area[data-seatno]",
    ],
    # 선택 불가 좌석(위 seat 셀렉터가 너무 넓게 잡을 때 제외용)
    "seat_unavailable_class": ["unable", "disabled", "reserved", "sold", "impossible"],
    # 좌석 선택 후 다음 단계로
    "next_step": [
        "#btnNext",
        "a:has-text('다음')",
        "button:has-text('다음')",
        "a:has-text('결제하기')",
    ],
    # 결제 페이지에 도달했음을 알려주는 표식(누르지 않고 확인만 한다)
    "payment_marker": [
        "text=결제수단",
        "#divPayment",
        "text=최종 결제금액",
    ],
    # 로그인 상태 확인용
    "logged_out_marker": [
        "a:has-text('로그인')",
        "text=로그인이 필요",
    ],
}


@dataclass
class BookResult:
    stage: str  # opened | seats_selected | payment_ready | failed
    message: str
    screenshot: str = ""


class Booker:
    def __init__(self, cfg: BookingConfig) -> None:
        self.cfg = cfg
        self.selectors = {**DEFAULT_SELECTORS, **(cfg.selectors or {})}
        self.timeout_ms = int(cfg.step_timeout_seconds * 1000)
        self.keep_open_seconds = 900.0

    # ------------------------------------------------------------------ api
    def login(self) -> None:
        """브라우저를 띄워 직접 로그인시키고, 세션을 프로필 디렉터리에 저장한다."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            ctx = self._launch(p, headless=False)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
            print(
                "\n브라우저에서 CGV 로그인을 완료하세요.\n"
                "(자동입력 없이 직접 입력합니다 — 비밀번호는 이 프로그램이 다루지 않습니다.)\n"
                "로그인이 끝나면 이 터미널에서 Enter 를 누르세요..."
            )
            try:
                input()
            except EOFError:
                time.sleep(120)
            ctx.close()
        log.info("로그인 세션을 %s 에 저장했습니다.", self.cfg.user_data_dir)

    def book(self, showtime: Showtime, notifier=None) -> BookResult:
        from playwright.sync_api import sync_playwright

        url = self._booking_url(showtime)
        log.info("예매 페이지 여는 중: %s", url)

        with sync_playwright() as p:
            ctx = self._launch(p, headless=self.cfg.headless)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.set_default_timeout(self.timeout_ms)
            result = BookResult("failed", "시작 전 실패")
            try:
                page.goto(url, wait_until="domcontentloaded")
                result = BookResult("opened", "예매 페이지를 열었습니다.")

                if self._visible_any(page, self.selectors["logged_out_marker"], timeout=2000):
                    result = BookResult(
                        "opened",
                        "로그인이 풀렸습니다. `python -m cgv_watch login` 으로 다시 로그인하세요.",
                    )
                elif self.cfg.mode == "seat_select":
                    result = self._select_seats(page, showtime)
            except Exception as exc:  # 어떤 단계에서 막혀도 창은 남긴다
                log.exception("자동화 중 오류")
                result = BookResult("failed", f"자동화 중 오류: {exc}")
            finally:
                result.screenshot = self._screenshot(page, showtime)

            self._report(result, showtime, url, notifier)
            self._hold_open(page)
            try:
                ctx.close()
            except Exception:
                pass
        return result

    # -------------------------------------------------------------- internals
    def _launch(self, p, headless: bool):
        profile = Path(self.cfg.user_data_dir).expanduser()
        profile.mkdir(parents=True, exist_ok=True)
        return p.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=headless,
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            viewport={"width": 1400, "height": 1000},
            args=["--disable-blink-features=AutomationControlled"],
        )

    def _booking_url(self, showtime: Showtime) -> str:
        if self.cfg.url_template:
            return self.cfg.url_template.format(
                theater_code=showtime.theater_code,
                play_ymd=showtime.play_ymd,
                screen_code=showtime.screen_code,
                play_num=showtime.play_num,
                movie_idx=showtime.movie_idx,
            )
        return showtime.booking_url()

    def _frames(self, page):
        """메인 프레임 + 모든 iframe. CGV 예매 UI 는 iframe 안에 있는 경우가 많다."""
        return [page.main_frame, *[f for f in page.frames if f is not page.main_frame]]

    def _visible_any(self, page, selectors: list[str], timeout: int = 3000):
        """여러 프레임 × 여러 셀렉터 중 처음으로 보이는 locator 를 돌려준다."""
        deadline = time.time() + timeout / 1000
        while time.time() < deadline:
            for frame in self._frames(page):
                for sel in selectors:
                    try:
                        loc = frame.locator(sel).first
                        if loc.count() and loc.is_visible():
                            return loc
                    except Exception:
                        continue
            page.wait_for_timeout(250)
        return None

    def _seat_locators(self, page):
        """예매 가능한 좌석 요소들을 (frame, locator 리스트)로 찾는다."""
        bad = [c.lower() for c in self.selectors["seat_unavailable_class"]]
        deadline = time.time() + self.timeout_ms / 1000
        while time.time() < deadline:
            for frame in self._frames(page):
                for sel in self.selectors["seat"]:
                    try:
                        loc = frame.locator(sel)
                        n = loc.count()
                    except Exception:
                        continue
                    if n < 5:  # 좌석표라면 최소 수십 개는 나온다
                        continue
                    seats = []
                    for i in range(n):
                        item = loc.nth(i)
                        try:
                            cls = (item.get_attribute("class") or "").lower()
                            if any(b in cls for b in bad):
                                continue
                            box = item.bounding_box()
                        except Exception:
                            continue
                        if box and box["width"] > 0:
                            seats.append((item, box))
                    if len(seats) >= 1:
                        log.info("좌석 %d개 발견 (셀렉터: %s)", len(seats), sel)
                        return seats
            page.wait_for_timeout(500)
        return []

    def _pick(self, seats, count: int, prefer_adjacent: bool):
        """붙어 있는 좌석 우선으로 count 개를 고른다. 좌표 기준이라 마크업에 덜 민감하다."""
        if count <= 1 or not prefer_adjacent:
            return [s for s, _ in seats[:count]]

        rows: dict[int, list] = {}
        for item, box in seats:
            row_key = round(box["y"] / max(box["height"], 1))
            rows.setdefault(row_key, []).append((item, box))

        for _, row in sorted(rows.items()):
            row.sort(key=lambda t: t[1]["x"])
            run = [row[0]]
            for prev, cur in zip(row, row[1:]):
                gap = cur[1]["x"] - (prev[1]["x"] + prev[1]["width"])
                run = run + [cur] if gap <= prev[1]["width"] * 1.5 else [cur]
                if len(run) >= count:
                    return [item for item, _ in run[:count]]
            if len(run) >= count:
                return [item for item, _ in run[:count]]

        log.info("붙어 있는 %d석을 못 찾아 흩어진 좌석으로 고릅니다.", count)
        return [s for s, _ in seats[:count]]

    def _select_seats(self, page, showtime: Showtime) -> BookResult:
        count = max(1, self.cfg.seat_count)

        # 1) 인원 선택 (성인 N명)
        plus = self._visible_any(page, self.selectors["adult_plus"], timeout=8000)
        if plus:
            for _ in range(count):
                try:
                    plus.click()
                    page.wait_for_timeout(200)
                except Exception:
                    break
            log.info("성인 %d명 선택 시도 완료", count)
        else:
            log.info("인원 선택 UI 를 못 찾았습니다 — 좌석 단계로 바로 진행합니다.")

        # 2) 좌석 선택
        seats = self._seat_locators(page)
        if not seats:
            return BookResult(
                "opened",
                "좌석표를 못 읽었습니다. 창은 열려 있으니 직접 좌석을 고르세요. "
                "(README 의 '셀렉터 맞추기' 참고)",
            )
        if len(seats) < count:
            return BookResult(
                "opened",
                f"남은 좌석이 {len(seats)}개뿐이라 {count}석을 잡을 수 없습니다. 직접 확인하세요.",
            )

        chosen = self._pick(seats, count, self.cfg.prefer_adjacent)
        clicked = 0
        for seat in chosen:
            try:
                seat.click(timeout=3000)
                clicked += 1
                page.wait_for_timeout(200)
            except Exception:
                log.warning("좌석 클릭 실패 — 그 사이 다른 사람이 잡았을 수 있습니다.")
        if clicked < count:
            return BookResult(
                "opened", f"{count}석 중 {clicked}석만 선택됐습니다. 나머지는 직접 골라주세요."
            )

        # 3) 결제 직전 단계까지만
        nxt = self._visible_any(page, self.selectors["next_step"], timeout=5000)
        if not nxt:
            return BookResult("seats_selected", f"{clicked}석 선택 완료. '다음' 버튼을 직접 누르세요.")
        try:
            nxt.click()
        except Exception:
            return BookResult("seats_selected", f"{clicked}석 선택 완료. '다음' 버튼을 직접 누르세요.")

        page.wait_for_timeout(2000)
        if self._visible_any(page, self.selectors["payment_marker"], timeout=8000):
            return BookResult(
                "payment_ready",
                f"{clicked}석 선택 + 결제 페이지 진입 완료. **결제는 직접 확인하고 눌러주세요.**",
            )
        return BookResult("seats_selected", f"{clicked}석 선택 완료. 다음 단계를 직접 진행하세요.")

    def _screenshot(self, page, showtime: Showtime) -> str:
        try:
            out = Path(self.cfg.screenshot_dir).expanduser()
            out.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            path = out / f"{stamp}-{showtime.key.replace(':', '_')}.png"
            page.screenshot(path=str(path), full_page=False)
            return str(path)
        except Exception:
            return ""

    def _report(self, result: BookResult, showtime: Showtime, url: str, notifier) -> None:
        icon = {"payment_ready": "💳", "seats_selected": "🪑", "opened": "🌐"}.get(result.stage, "⚠️")
        log.info("%s %s", icon, result.message)
        if notifier:
            notifier.send(
                title=f"{icon} CGV 예매 진행 상황",
                body=f"{showtime.describe()}\n{result.message}",
                url=url,
            )

    def _hold_open(self, page) -> None:
        """사람이 마무리할 수 있게 창을 열어둔다. 창을 닫으면 즉시 빠져나온다."""
        if self.cfg.headless:
            return
        deadline = time.time() + self.keep_open_seconds
        log.info("브라우저를 %.0f분간 열어둡니다. 결제를 마치고 창을 닫으세요.", self.keep_open_seconds / 60)
        while time.time() < deadline:
            try:
                if page.is_closed():
                    return
                page.wait_for_timeout(1000)
            except Exception:
                return
