"""CGV를 흉내 낸 로컬 목(mock) 서버. 실제 사이트 없이 전체 흐름을 돌려보기 위한 것.

제공하는 엔드포인트
  /common/showtimes/iframeTheater.aspx  상영시간표 (처음엔 매진 → N번째 폴링부터 좌석 오픈)
  /ticket/                              인원 선택 + 좌석표
  /ticket/payment                       결제 페이지 (여기서 자동화가 멈춰야 정상)

사용:
  python tools/mock_cgv_server.py --port 8899 --open-after 2 &
  CGV_BASE_URL=http://127.0.0.1:8899 python -m cgv_watch watch -c <설정>

주의: 이건 어디까지나 흉내다. 실제 CGV 마크업과 일치한다는 보장은 없고,
자기 코드가 "빈자리 감지 → 알림 → 좌석 클릭 → 결제 직전 정지"까지
제대로 이어지는지 확인하는 용도다.
"""

from __future__ import annotations

import argparse
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

STATE = {"polls": 0, "open_after": 2, "seats_open": 12, "rows": 6, "cols": 14, "taken": set()}
LOCK = threading.Lock()


def showtimes_html(play_ymd: str, remain: int) -> str:
    """CGV 상영시간표 iframe 구조를 흉내 낸 HTML."""

    def block(title, hall, start, end, remain, num, screen, movie_idx):
        return f"""
        <li><div class="col-times">
          <div class="info-movie"><a href="#"><strong>{title}</strong></a></div>
          <div class="type-hall">
            <div class="info-hall"><ul><li>{hall}</li><li>1관</li><li>총 620석</li></ul></div>
            <div class="info-timetable"><ul><li>
              <a href="#none" class="btn-reserve"
                 data-playstarttime="{start}" data-playendtime="{end}"
                 data-seatremaincnt="{remain}" data-theatercode="0013"
                 data-screencode="{screen}" data-playymd="{play_ymd}"
                 data-playnum="{num}" data-movieidx="{movie_idx}"
                 data-moviecdgroup="{movie_idx}"><em>{start[:2]}:{start[2:]}</em></a>
            </li></ul></div>
          </div>
        </div></li>"""

    return f"""<div class="sect-showtimes"><ul>
      {block("오디세이", "IMAX 2D", "1100", "1400", remain, "2", "0001", "99001")}
      {block("오디세이", "IMAX 2D", "1430", "1730", 30, "3", "0001", "99001")}
      {block("오디세이", "2D", "1100", "1400", 50, "9", "0006", "99001")}
      {block("다른영화", "IMAX 2D", "1100", "1300", 40, "7", "0001", "10001")}
    </ul></div>"""


def ticket_html() -> str:
    """인원 선택 + 좌석표. 매진 좌석은 .unable 로 막아둔다."""
    rows, cols = STATE["rows"], STATE["cols"]
    open_seats = STATE["seats_open"]
    cells = []
    idx = 0
    for r in range(rows):
        row_letter = chr(ord("A") + r)
        for c in range(cols):
            idx += 1
            # 마지막 줄 가운데에만 연속으로 자리를 열어 "붙은 자리" 선택을 검증한다.
            available = r == rows - 1 and 4 <= c < 4 + open_seats
            cls = "seat" if available else "seat unable"
            cells.append(
                f'<a href="#" class="{cls}" data-seatno="{row_letter}{c + 1}" '
                f'style="display:inline-block;width:22px;height:22px;margin:3px;'
                f'background:{"#2ecc71" if available else "#444"};" '
                f'onclick="pick(this);return false;">&nbsp;</a>'
            )
        cells.append("<br>")
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>CGV 예매 (mock)</title><style>
body{{font-family:sans-serif;background:#111;color:#eee;padding:24px}}
.screen{{background:#666;text-align:center;padding:6px;margin:16px auto;width:460px}}
#btnNext{{display:inline-block;margin-top:20px;padding:12px 28px;background:#e60012;
color:#fff;text-decoration:none;border-radius:4px}}
.sel{{outline:3px solid #ffd200}}
.count{{font-size:20px;margin:0 12px}}
</style></head><body>
<h2>오디세이 · CGV 용산아이파크몰 · IMAX 1관 · 11:00</h2>
<div id="personCountAdult">성인 <span class="count" id="adultCount">0</span>
  <a href="#" class="btn-plus" onclick="plus();return false;">＋</a></div>
<div class="screen">S C R E E N</div>
<div id="seatMap">{"".join(cells)}</div>
<p>선택한 좌석: <b id="picked">없음</b></p>
<a href="#" id="btnNext" onclick="next();return false;">다음</a>
<script>
var picked=[];
function plus(){{var e=document.getElementById('adultCount');e.textContent=+e.textContent+1;}}
function pick(a){{
  if(a.className.indexOf('unable')>=0) return;
  a.className+=' sel'; picked.push(a.dataset.seatno);
  document.getElementById('picked').textContent=picked.join(', ');
}}
function next(){{ location.href='/ticket/payment?seats='+picked.join(','); }}
</script></body></html>"""


def payment_html(seats: str) -> str:
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>결제 (mock)</title><style>body{{font-family:sans-serif;background:#111;color:#eee;padding:32px}}
.box{{border:1px solid #444;padding:20px;max-width:520px}}
.pay{{margin-top:20px;padding:14px 30px;background:#e60012;color:#fff;border:0;font-size:16px}}
</style></head><body>
<h2>결제수단</h2>
<div class="box">
  <p>오디세이 · IMAX 1관 · 11:00</p>
  <p>선택 좌석: <b>{seats or "-"}</b></p>
  <p>최종 결제금액: <b>26,000원</b></p>
  <label><input type="radio" checked> 신용카드</label>
  <button class="pay">결제하기</button>
</div>
<p style="color:#ffd200">※ 자동화는 여기까지만 오고 멈춰야 정상입니다.</p>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        qs = parse_qs(url.query)

        if url.path.startswith("/common/showtimes/"):
            with LOCK:
                STATE["polls"] += 1
                n = STATE["polls"]
                remain = STATE["seats_open"] if n > STATE["open_after"] else 0
            play_ymd = (qs.get("date") or ["20260814"])[0]
            print(f"  [mock] 상영시간표 요청 #{n} → 목표 회차 잔여 {remain}석")
            return self._send(showtimes_html(play_ymd, remain))

        if url.path.rstrip("/") == "/ticket/payment".rstrip("/") or url.path.startswith(
            "/ticket/payment"
        ):
            seats = (qs.get("seats") or [""])[0]
            print(f"  [mock] 결제 페이지 진입 — 좌석 {seats}")
            return self._send(payment_html(seats))

        if url.path.startswith("/ticket"):
            print(f"  [mock] 예매 페이지 요청 {url.query}")
            return self._send(ticket_html())

        return self._send("<html><body>mock cgv</body></html>")

    def _send(self, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # 기본 액세스 로그는 끈다
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description="CGV 목 서버")
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--open-after", type=int, default=2, help="N번째 폴링 이후 좌석 오픈")
    ap.add_argument("--seats", type=int, default=12, help="열릴 좌석 수")
    args = ap.parse_args()
    STATE["open_after"] = args.open_after
    STATE["seats_open"] = args.seats
    print(f"[mock] http://127.0.0.1:{args.port} — {args.open_after}번째 폴링 뒤 {args.seats}석 오픈")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
