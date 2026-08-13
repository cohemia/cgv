"""커맨드라인 진입점."""

from __future__ import annotations

import argparse
import logging
import os
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


def verify_login_session(booking_cfg) -> tuple[bool, str]:
    """저장된 프로필이 실제로 CGV 로그인 상태인지 확인한다.

    프로필 폴더가 있다는 것만으로는 부족하다. `login` 을 실행했다가 로그인을 끝내지
    않았거나 세션이 만료된 경우에도 폴더는 남아 있어서, 정작 새벽에 빈자리가 났을 때
    로그인 화면에서 멈춘다. 그래서 실제로 페이지를 열어 확인한다.
    """
    from .models import BASE_URL

    profile = Path(booking_cfg.user_data_dir).expanduser()
    if not profile.is_dir() or not any(profile.iterdir()):
        return False, "`./cgv login` 을 먼저 실행하세요. (평소 쓰는 크롬 로그인과는 별개입니다)"

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False, "playwright 가 없어 확인하지 못했습니다."

    try:
        with sync_playwright() as p:
            kwargs = {
                "user_data_dir": str(profile),
                "headless": True,
                "locale": "ko-KR",
                "timezone_id": "Asia/Seoul",
            }
            if booking_cfg.browser_executable:
                kwargs["executable_path"] = booking_cfg.browser_executable
            ctx = p.chromium.launch_persistent_context(**kwargs)
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(BASE_URL, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(1500)
                html = page.content()
            finally:
                ctx.close()
    except Exception as exc:
        msg = str(exc)
        if "ProcessSingleton" in msg or "SingletonLock" in msg or "already in use" in msg:
            return False, "감시(watch)가 이미 실행 중이라 확인할 수 없습니다. 먼저 종료하세요."
        return False, f"확인 실패: {msg[:160]}"

    if "로그아웃" in html or "마이페이지" in html:
        return True, ""
    return False, (
        "프로필은 있지만 로그인 상태가 아닙니다 (세션 만료 또는 로그인 미완료). "
        "`./cgv login` 을 다시 실행하세요."
    )


def extract_chat_ids(payload: dict) -> list[tuple[str, str]]:
    """getUpdates 응답에서 (chat_id, 표시이름) 목록을 뽑는다."""
    found: dict[str, str] = {}
    for update in payload.get("result") or []:
        for key in ("message", "edited_message", "channel_post", "my_chat_member"):
            chat = (update.get(key) or {}).get("chat") or {}
            cid = chat.get("id")
            if cid is None:
                continue
            name = (
                chat.get("title")
                or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
                or chat.get("username")
                or "(이름 없음)"
            )
            found[str(cid)] = name
    return sorted(found.items())


def cmd_telegram_id(args) -> int:
    """봇 토큰을 검사하고 chat id 를 찾아준다. 주소창에 URL 을 직접 치는 것보다 안전하다."""
    import requests

    token = (args.token or os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        print("토큰이 없습니다. --token 으로 주거나 .env 의 TELEGRAM_BOT_TOKEN 을 채우세요.",
              file=sys.stderr)
        return 1
    if ":" not in token:
        print(
            "토큰 형식이 아닙니다. 숫자와 콜론이 함께 있어야 합니다 (예: 8012345678:AAEh...).\n"
            "BotFather 메시지에서 'Use this token to access the HTTP API:' 아래 한 줄을 통째로 쓰세요.",
            file=sys.stderr,
        )
        return 1

    api = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        res = requests.get(api, timeout=15)
    except requests.RequestException as exc:
        print(f"텔레그램 접속 실패: {exc}", file=sys.stderr)
        return 1

    if res.status_code == 404:
        print(
            "❌ 토큰이 유효하지 않습니다 (404).\n"
            "   흔한 원인:\n"
            "     · /revoke 로 폐기한 옛 토큰을 쓰고 있음 → BotFather 의 최신 토큰을 쓰세요\n"
            "     · 복사할 때 앞뒤가 잘림 → 콜론 앞 숫자부터 끝까지 통째로 복사\n"
            "     · 예시 문구(<토큰> 같은 것)를 그대로 붙여넣음",
            file=sys.stderr,
        )
        return 1
    try:
        payload = res.json()
    except ValueError:
        print(f"응답을 이해할 수 없습니다: {res.text[:200]}", file=sys.stderr)
        return 1
    if not payload.get("ok"):
        print(f"❌ 텔레그램 오류: {payload.get('description', payload)}", file=sys.stderr)
        return 1

    chats = extract_chat_ids(payload)
    if not chats:
        print(
            "✅ 토큰은 정상입니다. 다만 대화 기록이 비어 있습니다.\n"
            "   폰에서 봇 대화방을 열고 '시작(START)' 을 누른 뒤 아무 메시지나 한 번 보내고,\n"
            "   이 명령을 다시 실행하세요."
        )
        return 1

    print("✅ 토큰 정상. 찾은 chat id:\n")
    for cid, name in chats:
        print(f"   {cid}\t{name}")

    if args.save:
        env_path = Path(args.env_file)
        lines = []
        if env_path.is_file():
            lines = [
                ln
                for ln in env_path.read_text(encoding="utf-8").splitlines()
                if not ln.startswith(("TELEGRAM_BOT_TOKEN=", "TELEGRAM_CHAT_ID="))
            ]
        lines += [f"TELEGRAM_BOT_TOKEN={token}", f"TELEGRAM_CHAT_ID={chats[0][0]}"]
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\n{env_path} 에 저장했습니다 (chat id {chats[0][0]}).")
        print("`python -m cgv_watch test-notify` 로 실제로 오는지 확인하세요.")
    else:
        print("\n--save 를 붙이면 .env 에 바로 저장합니다.")
    return 0


def cmd_check(args) -> int:
    """실전 투입 전 자가진단. 실제 CGV에 붙어 설정이 맞는지 한 번에 확인한다."""
    cfg = _load_config(args.config)
    ok = True

    def line(passed: bool, label: str, detail: str = "") -> bool:
        print(f"{'✅' if passed else '❌'} {label}" + (f"\n     {detail}" if detail else ""))
        return passed

    print("\n══════ CGV 빈자리 감시 자가진단 ══════\n")

    # 1. CGV 접속 + 상영시간표 파싱
    target = cfg.targets[0]
    play_ymd = target.dates[0]
    client = CgvClient(timeout=cfg.poll.request_timeout)
    showtimes = []
    try:
        html = client.fetch_showtimes_html(target.theater_code, play_ymd)
        ok &= line(True, f"CGV 접속 ({len(html):,} bytes 수신)")
        showtimes = parse_showtimes(html, target.theater_code, play_ymd)
        ok &= line(
            bool(showtimes),
            f"상영시간표 파싱 — {len(showtimes)}개 회차",
            "" if showtimes else f"`python -m cgv_watch dump --theater {target.theater_code} "
            f"--date {play_ymd}` 로 원본을 확인하세요. 휴관일이거나 마크업이 바뀐 것입니다.",
        )
    except Exception as exc:
        ok &= line(False, "CGV 접속", str(exc)[:200])

    # 2. 극장 코드가 실제로 그 극장인지
    if showtimes:
        halls = sorted({s.screen_name for s in showtimes if s.screen_name})
        movies = sorted({s.movie_name for s in showtimes if s.movie_name})
        line(True, f"극장 {target.theater_code} 상영 중", f"영화: {', '.join(movies[:6])}")
        line(True, "상영관 종류", ", ".join(halls[:8]) or "(정보 없음)")

    # 3. 타깃 조건에 실제로 걸리는 회차가 있는지 — 가장 자주 틀리는 부분
    for t in cfg.targets:
        for ymd in t.dates:
            try:
                sts = showtimes if ymd == play_ymd and t is target else client.get_showtimes(
                    t.theater_code, ymd
                )
            except Exception as exc:
                ok &= line(False, f"[{t.name}] {ymd} 조회", str(exc)[:150])
                continue
            matched = filter_showtimes(
                sts,
                movie_contains=t.movie_contains,
                movie_idx=t.movie_idx,
                screen_contains=t.screen_contains,
                time_from=t.time_from,
                time_to=t.time_to,
            )
            ok &= line(
                bool(matched),
                f"[{t.name}] {ymd} — 조건 일치 {len(matched)}회차",
                ""
                if matched
                else "조건이 너무 좁습니다. movie_contains / screen_contains / "
                "time_from~time_to 를 넓혀보세요.",
            )
            for s in matched:
                state = f"{s.seat_remain}석 남음" if s.seat_remain else "매진 (감시 대상)"
                print(f"     · {s.start_hhmm} {s.screen_name} — {state}")
                if s.seat_remain >= t.min_seats:
                    print(f"       지금 바로 예매 가능: {s.booking_url()}")

    # 4. 알림 채널
    notifier = build_notifiers(cfg.notify)
    if not notifier:
        ok &= line(False, "알림 채널", "활성화된 채널이 없습니다.")
    elif args.notify:
        try:
            notifier.send("🎟️ 자가진단 알림", "이 메시지가 보이면 알림은 정상입니다.", "")
            line(True, f"알림 발송 ({len(notifier.notifiers)}개 채널) — 실제로 왔는지 확인하세요")
        except Exception as exc:
            ok &= line(False, "알림 발송", str(exc)[:150])
    else:
        line(True, f"알림 채널 {len(notifier.notifiers)}개 설정됨 (--notify 로 실제 발송 테스트)")

    # 5. 자동 예매 준비 상태
    if cfg.booking.enabled and cfg.booking.mode != "off":
        try:
            import playwright  # noqa: F401

            line(True, "playwright 설치됨")
        except ImportError:
            ok &= line(False, "playwright 미설치", "pip install playwright && playwright install chromium")
        logged_in, why = verify_login_session(cfg.booking)
        ok &= line(logged_in, "CGV 로그인 세션 (실제 접속해서 확인)", why)
        if cfg.booking.seat_count != cfg.targets[0].min_seats:
            line(
                False,
                f"인원 불일치 — seat_count={cfg.booking.seat_count}, "
                f"min_seats={cfg.targets[0].min_seats}",
                "두 값을 같게 맞추세요. 다르면 1석 알림 받고 2석 잡으려다 실패합니다.",
            )
    else:
        line(True, "자동 예매 꺼짐 — 알림만 동작합니다")

    print("\n" + ("모두 통과. `python -m cgv_watch watch` 로 감시를 시작하세요." if ok
                  else "❌ 항목을 먼저 해결하세요."))
    return 0 if ok else 1


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

    ck = sub.add_parser("check", help="실전 투입 전 자가진단 (실제 CGV에 접속해 설정 검증)")
    ck.add_argument("-c", "--config", default="config.yaml")
    ck.add_argument("--notify", action="store_true", help="알림도 실제로 한 번 보내본다")
    ck.set_defaults(func=cmd_check)

    lg = sub.add_parser("login", help="브라우저를 띄워 CGV 로그인 세션 저장")
    lg.add_argument("-c", "--config", default="config.yaml")
    lg.set_defaults(func=cmd_login)

    tg = sub.add_parser("telegram-id", help="봇 토큰을 검사하고 chat id 를 찾아준다")
    tg.add_argument("--token", help="봇 토큰 (생략하면 .env 의 TELEGRAM_BOT_TOKEN)")
    tg.add_argument("--save", action="store_true", help="찾은 값을 .env 에 저장")
    tg.add_argument("--env-file", default=".env")
    tg.set_defaults(func=cmd_telegram_id)

    n = sub.add_parser("test-notify", help="알림 채널 점검")
    n.add_argument("-c", "--config", default="config.yaml")
    n.set_defaults(func=cmd_test_notify)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    load_dotenv(args.env)
    return args.func(args)
