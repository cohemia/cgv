"""커맨드라인 진입점."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .client import CgvClient, filter_showtimes, parse_showtimes
from .config import Config, ConfigError, load_dotenv, resolve_dates
from .notifiers import build_notifiers
from .watcher import Watcher


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def _load_config(path: str) -> Config:
    try:
        return Config.load(path)
    except ConfigError as exc:
        print(f"설정 오류: {exc}", file=sys.stderr)
        raise SystemExit(2)


def _build_booker(cfg: Config):
    if not cfg.booking.enabled or cfg.booking.mode == "off":
        return None
    try:
        import playwright  # noqa: F401
    except ImportError:
        logging.getLogger(__name__).warning(
            "booking.enabled=true 인데 playwright 가 없습니다. 알림만 동작합니다. "
            "설치: pip install playwright && playwright install chromium"
        )
        return None
    from .booker import Booker

    return Booker(cfg.booking)


def cmd_watch(args) -> int:
    cfg = _load_config(args.config)
    watcher = Watcher(
        cfg,
        client=CgvClient(timeout=cfg.poll.request_timeout),
        notifier=build_notifiers(cfg.notify),
        booker=_build_booker(cfg),
    )
    try:
        watcher.run(once=args.once)
    except KeyboardInterrupt:
        print("\n중단했습니다.")
    return 0


def cmd_showtimes(args) -> int:
    client = CgvClient()
    for play_ymd in resolve_dates(args.date):
        showtimes = client.get_showtimes(args.theater, play_ymd)
        showtimes = filter_showtimes(
            showtimes,
            movie_contains=args.movie or "",
            screen_contains=args.screen or "",
        )
        print(f"\n=== {args.theater} / {play_ymd} — {len(showtimes)}개 회차 ===")
        for s in showtimes:
            flag = "🟢" if s.seat_remain > 0 else "🔴"
            print(f"{flag} {s.describe()}")
            if args.urls:
                print(f"   {s.booking_url()}")
    return 0


def cmd_theaters(args) -> int:
    for code, name in CgvClient().get_theaters():
        if not args.query or args.query in name:
            print(f"{code}\t{name}")
    return 0


def cmd_dump(args) -> int:
    client = CgvClient()
    for play_ymd in resolve_dates(args.date):
        html = client.fetch_showtimes_html(args.theater, play_ymd)
        out = Path(args.out or f"dumps/{args.theater}-{play_ymd}.html")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
        found = len(parse_showtimes(html, args.theater, play_ymd))
        print(f"{out} 저장 ({len(html):,} bytes, 회차 {found}개 파싱됨)")
    return 0


def cmd_login(args) -> int:
    cfg = _load_config(args.config)
    from .booker import Booker

    Booker(cfg.booking).login()
    return 0


def cmd_test_notify(args) -> int:
    cfg = _load_config(args.config)
    notifier = build_notifiers(cfg.notify)
    if not notifier:
        print("활성화된 알림 채널이 없습니다.", file=sys.stderr)
        return 1
    notifier.send(
        title="🎟️ CGV 빈자리 알림 테스트",
        body="이 메시지가 보이면 알림 설정이 정상입니다.",
        url="http://www.cgv.co.kr/ticket/",
    )
    print("테스트 알림을 보냈습니다.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cgv_watch",
        description="CGV 상영회차 잔여좌석을 감시하다가 빈자리가 나면 알리고 예매 페이지를 자동으로 띄웁니다.",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="디버그 로그")
    p.add_argument("--env", default=".env", help=".env 파일 경로 (기본: .env)")
    sub = p.add_subparsers(dest="command", required=True)

    w = sub.add_parser("watch", help="빈자리 감시 시작")
    w.add_argument("-c", "--config", default="config.yaml")
    w.add_argument("--once", action="store_true", help="한 번만 확인하고 종료")
    w.set_defaults(func=cmd_watch)

    s = sub.add_parser("showtimes", help="상영시간표와 잔여좌석을 한 번 조회")
    s.add_argument("--theater", required=True, help="극장 코드 (예: 0013)")
    s.add_argument("--date", default="today", help="YYYY-MM-DD / today / tomorrow / +3")
    s.add_argument("--movie", help="영화명 부분 일치")
    s.add_argument("--screen", help="상영관명 부분 일치 (예: IMAX)")
    s.add_argument("--urls", action="store_true", help="예매 딥링크도 출력")
    s.set_defaults(func=cmd_showtimes)

    t = sub.add_parser("theaters", help="극장 코드 목록")
    t.add_argument("query", nargs="?", help="극장명 부분 일치 필터")
    t.set_defaults(func=cmd_theaters)

    d = sub.add_parser("dump", help="상영시간표 원본 HTML 저장 (파싱이 깨질 때 확인용)")
    d.add_argument("--theater", required=True)
    d.add_argument("--date", default="today")
    d.add_argument("-o", "--out")
    d.set_defaults(func=cmd_dump)

    lg = sub.add_parser("login", help="브라우저를 띄워 CGV 로그인 세션 저장")
    lg.add_argument("-c", "--config", default="config.yaml")
    lg.set_defaults(func=cmd_login)

    n = sub.add_parser("test-notify", help="알림 채널 점검")
    n.add_argument("-c", "--config", default="config.yaml")
    n.set_defaults(func=cmd_test_notify)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    load_dotenv(args.env)
    return args.func(args)
