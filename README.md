# CGV 빈자리 감시 · 예매 보조

매진된 CGV 회차의 **취소표(빈자리)를 감시**하다가 자리가 나면 즉시 알리고,
로그인된 브라우저로 **예매 페이지를 열어 좌석까지 자동 선택**해줍니다.
**결제는 자동으로 하지 않습니다** — 마지막 결제 버튼은 직접 누릅니다.

```
매진 감시  ──▶  빈자리 감지  ──▶  텔레그램/데스크탑 알림
                            └──▶  브라우저 자동 실행 → 인원·좌석 선택 → 결제 화면에서 정지
```

---

## 먼저 알아둘 것

- **결제 자동화는 넣지 않았습니다.** CGV 결제는 보안 키패드·간편결제 본인인증이 걸려 있어
  자동화 성공률이 낮고, 잘못 눌리면 실제로 돈이 나갑니다. 좌석을 잡아두는 것까지가
  실질적인 승부처라 거기까지만 자동화했습니다.
- **셀렉터는 검증되지 않은 기본값입니다.** 이 코드를 만든 환경에서 `www.cgv.co.kr` 로의
  네트워크가 차단되어 있어 실제 응답으로 확인하지 못했습니다. 상영시간표 파서는 특정
  클래스 구조 대신 `data-seatremaincnt` 같은 data 속성에 의존하도록 느슨하게 짜뒀지만,
  안 맞으면 아래 [파싱이 안 될 때](#파싱이-안-될-때) / [셀렉터 맞추기](#셀렉터-맞추기)를 보세요.
- **개인 예매 용도로만.** 폴링 간격을 과하게 줄이면 CGV 입장에서는 그냥 공격 트래픽이고,
  IP 차단으로 이어집니다. 기본값 30초 + 지터를 그대로 쓰길 권합니다. 되팔이 목적의
  대량 선점에는 쓰지 마세요.

---

## 바로 쓰기 (미리 만들어둔 설정)

`presets/` 에 완성된 설정이 있습니다. 복사만 하면 됩니다.

```bash
cp presets/odyssey-yongsan-20260814.yaml config.yaml
python -m cgv_watch check --notify   # ← 실전 투입 전 자가진단 (아래 참고)
python -m cgv_watch watch
```

| 프리셋 | 대상 |
|---|---|
| `odyssey-yongsan-20260814.yaml` | 8/14 CGV 용산아이파크몰 IMAX 오전 11시 〈오디세이〉, 1인 |

---

## 설치

**한 번에 설치** — 파이썬 확인, 가상환경, 패키지, 브라우저, 설정 파일, 텔레그램까지 다 잡아줍니다.

```bash
# macOS / Linux
bash setup.sh

# Windows — 탐색기에서 setup.bat 더블클릭, 또는
setup.bat
```

<details>
<summary>직접 하고 싶다면</summary>

```bash
python3 -m venv .venv && source .venv/bin/activate   # 윈도우: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium        # 자동 예매를 쓸 때만
cp config.example.yaml config.yaml
cp .env.example .env
```
</details>

설치 후 새 터미널을 열 때마다 가상환경을 켜야 합니다.

```bash
source .venv/bin/activate      # 윈도우: .venv\Scripts\activate
```

---

## 5분 설정

### 1) 극장 코드 찾기

```bash
python -m cgv_watch theaters 용산
# 0013    CGV 용산아이파크몰
```

잘 안 나오면 브라우저에서 극장 페이지를 열고 주소창의 `theaterCode=` 값을 보면 됩니다.

### 2) 감시할 회차가 잡히는지 확인

```bash
python -m cgv_watch showtimes --theater 0013 --date 2026-08-20 --movie 아바타 --urls
# 🔴 아바타: 불과 재 | IMAX 2D 1관 | 08/20 19:00~22:00 | 0석/620
# 🟢 아바타: 불과 재 | IMAX 2D 1관 | 08/20 22:30~01:30 | 12석/620
```

🔴(0석)으로 보이는 회차가 바로 감시 대상입니다.

### 3) 텔레그램 봇 만들기

1. 텔레그램에서 **@BotFather** → `/newbot` → 토큰 복사
2. 만든 봇과 대화방을 열고 아무 메시지나 전송
3. `https://api.telegram.org/bot<토큰>/getUpdates` 접속 → `result[0].message.chat.id` 복사
4. `.env` 에 저장:

```env
TELEGRAM_BOT_TOKEN=123456:AAE...
TELEGRAM_CHAT_ID=987654321
```

확인:

```bash
python -m cgv_watch test-notify
```

### 4) 감시 대상 적기 (`config.yaml`)

```yaml
targets:
  - name: "아바타 IMAX 용산 주말 저녁"
    theater_code: "0013"
    dates: ["2026-08-20", "2026-08-21"]
    movie_contains: "아바타"     # 부분 일치
    screen_contains: "IMAX"     # 부분 일치, 비우면 전체 상영관
    time_from: "18:00"
    time_to: "23:59"
    min_seats: 2                # 2명이면 2 — 1석만 나면 안 알림
```

### 5) CGV 로그인 (자동 예매를 쓸 경우)

```bash
python -m cgv_watch login
```

브라우저가 뜨면 **직접** 로그인하고 터미널에서 Enter. 세션은 `.playwright/cgv-profile` 에
저장되고 이후 자동 실행 때 재사용됩니다. 이 프로그램은 아이디·비밀번호를 저장하거나
입력하지 않습니다. (프로필 디렉터리에는 로그인 쿠키가 들어 있으니 커밋·공유 금지.)

### 6) 자가진단 → 감시 시작

`watch` 를 켜두고 몇 시간 뒤에야 설정이 틀린 걸 알게 되는 게 최악입니다.
`check` 는 실제 CGV에 접속해 극장 코드·회차 매칭·알림·로그인 세션까지 한 번에 확인합니다.

```bash
python -m cgv_watch check --notify
```

```
══════ CGV 빈자리 감시 자가진단 ══════

✅ CGV 접속 (58,204 bytes 수신)
✅ 상영시간표 파싱 — 47개 회차
✅ 극장 0013 상영 중
     영화: 오디세이, ...
✅ 상영관 종류
     IMAX 2D 1관, 2D 6관, ...
✅ [오디세이 용산 IMAX 8/14 11시] 20260814 — 조건 일치 1회차
     · 11:00 IMAX 2D 1관 — 매진 (감시 대상)
✅ 알림 발송 (2개 채널) — 실제로 왔는지 확인하세요
✅ playwright 설치됨
✅ CGV 로그인 세션
```

`조건 일치 0회차` 가 나오면 극장 코드나 영화명·시간창이 틀린 것이니 감시를 켜도 영영
알림이 오지 않습니다. 여기서 잡으세요. 전부 ✅ 면 시작합니다.

```bash
python -m cgv_watch watch
```

### macOS 에서 밤새 돌릴 때

맥은 잠자기에 들어가면 폴링이 멈춥니다. `caffeinate -i` 를 앞에 붙이세요.

```bash
caffeinate -i python -m cgv_watch watch
```

- **덮개를 닫으면 `caffeinate` 를 써도 잠듭니다.** 덮개는 열어두세요.
- 전원 어댑터를 꽂아두세요. 배터리로는 몇 시간 못 갑니다.
- 데스크탑 알림이 안 뜨면 `시스템 설정 → 알림` 에서 **터미널**을 허용해주세요.
  (텔레그램 알림은 이와 무관하게 옵니다.)

---

## 동작 방식

- **폴링 대상**: `/common/showtimes/iframeTheater.aspx?theatercode=..&date=..`
  극장·날짜 하나당 요청 1회로 그 날 전 회차의 잔여좌석을 한 번에 읽습니다. 로그인 불필요.
- **엣지 트리거**: `0석 → N석`으로 **바뀌는 순간**에만 알립니다. 계속 열려 있는 회차를
  매번 다시 알리지 않습니다. 다시 매진됐다가 또 나오면 그때 다시 알립니다.
- **상태 저장**: `state.json` 에 회차별 마지막 상태를 남겨서, 프로그램을 재시작해도
  중복 알림이 뜨지 않습니다.
- **쿨다운**: 같은 회차는 `cooldown_minutes`(기본 10분) 안에 재알림하지 않습니다.
- **예매는 별도 스레드**: 브라우저가 뜬 동안에도 다른 회차 감시는 계속 돕니다.
  단, 동시에 두 건을 예매하지는 않습니다.

### 자동 예매가 하는 일 (`booking.mode: seat_select`)

1. 저장된 로그인 세션으로 예매 딥링크 열기
2. 성인 인원 `seat_count` 명 선택
3. 예매 가능한 좌석 중 **붙어 있는 자리 우선**으로 `seat_count` 개 클릭
   (좌석 좌표를 기준으로 같은 줄·연속 여부를 계산하므로 마크업 변화에 비교적 강함)
4. '다음' 눌러 결제 화면 진입 → **여기서 정지**, 알림 발송, 창은 15분간 열어둠

어느 단계에서 막히든 **브라우저는 그대로 열려 있고** 알림으로 상황을 알려줍니다.
자동화가 실패해도 사람이 이어서 하면 되도록 만든 구조입니다.

`booking.mode` 값:

| 값 | 동작 |
|---|---|
| `off` | 알림만 |
| `open_only` | 예매 페이지만 띄우고 좌석은 직접 |
| `seat_select` | 좌석까지 자동 선택 (기본) |

---

## 서버/도커로 24시간 감시

브라우저 자동화는 화면이 있는 로컬 PC용이고, 서버는 **알림 전용**으로 돌리는 조합을 권합니다.

`config.yaml` 을 서버용으로:

```yaml
notify:
  desktop: { enabled: false }
booking:
  enabled: false
state_file: "state/state.json"   # 볼륨에 저장해 재시작 후에도 상태 유지
```

```bash
docker compose up -d --build
docker compose logs -f
```

`.env` 의 텔레그램 토큰이 컨테이너로 전달되어 폰으로 알림이 옵니다.

---

## 실제 CGV 없이 전 과정 돌려보기 (데모)

CGV를 흉내 낸 로컬 목 서버가 들어 있습니다. 실제 예매 시즌이 오기 전에
"빈자리 감지 → 알림 → 좌석 클릭 → 결제 직전 정지"가 내 PC에서 이어지는지 확인할 수 있습니다.

```bash
# 터미널 1 — 목 CGV (3번째 폴링부터 12석이 열리도록)
python tools/mock_cgv_server.py --port 8899 --open-after 2 --seats 12

# 터미널 2 — 감시기를 목 서버로 붙여서 실행
cp presets/odyssey-yongsan-20260814.yaml demo.yaml   # dates 를 미래 날짜로 바꿔두세요
CGV_BASE_URL=http://127.0.0.1:8899 python -m cgv_watch watch -c demo.yaml
```

두어 번 폴링이 조용히 지나간 뒤 알림이 뜨고, 브라우저가 떠서 좌석을 고르고,
결제 화면에서 멈춥니다. 각 단계 스크린샷은 `screenshots/` 에 남습니다.

`CGV_BASE_URL` 은 데모 전용 환경변수입니다. 평소에는 설정하지 마세요.

---

## 문제 해결

### 파싱이 안 될 때

`회차를 하나도 못 읽었습니다` 로그가 뜨면 원본 HTML을 떠서 확인합니다.

```bash
python -m cgv_watch dump --theater 0013 --date 2026-08-20
# dumps/0013-20260820.html 저장 (회차 0개 파싱됨)
```

저장된 HTML에서 잔여좌석 숫자가 어떤 속성/태그에 있는지 확인하세요.
`data-seatremaincnt` 가 아닌 다른 이름이면 `cgv_watch/client.py` 의 `parse_showtimes`
쪽 속성명을 바꾸면 됩니다. 실제 HTML을 `tests/fixtures/` 에 넣고
`tests/test_parser.py` 를 돌리면 회귀도 같이 잡힙니다.

### 셀렉터 맞추기

좌석 자동 선택이 "좌석표를 못 읽었습니다"로 끝나면, 예매 페이지에서 F12로 좌석 요소의
클래스를 확인하고 `config.yaml` 에 덮어씁니다. 기본값은 `cgv_watch/booker.py` 의
`DEFAULT_SELECTORS` 에 있고, 필요한 항목만 바꾸면 됩니다.

```yaml
booking:
  selectors:
    seat:
      - "a.seat_bg:not(.no_seat)"
    seat_unavailable_class: ["no_seat", "sold"]
    next_step:
      - "#btnPayment"
```

실패 시점의 스크린샷이 `screenshots/` 에 남으니 어디서 막혔는지 보기 좋습니다.

### 알림이 안 올 때

```bash
python -m cgv_watch test-notify -v
```

텔레그램은 **봇에게 먼저 말을 걸어야** `chat_id` 가 생깁니다. 이 단계를 빼먹는 경우가 많습니다.

### 로그인이 자꾸 풀릴 때

`booking.user_data_dir` 이 매번 지워지고 있지 않은지 확인하고, `python -m cgv_watch login`
을 다시 실행하세요. CGV 세션은 영구적이지 않아 주기적으로 갱신이 필요합니다.

---

## 명령어

| 명령 | 설명 |
|---|---|
| `check` | 실전 투입 전 자가진단 (`--notify` 로 알림도 발송) |
| `watch` | 빈자리 감시 시작 (`--once` 로 1회만) |
| `showtimes` | 상영시간표·잔여좌석 조회 |
| `theaters [검색어]` | 극장 코드 목록 |
| `dump` | 상영시간표 원본 HTML 저장 |
| `login` | CGV 로그인 세션 저장 |
| `test-notify` | 알림 채널 점검 |

## 개발

```bash
pip install pytest && python -m pytest tests -q
```

테스트 픽스처(`tests/fixtures/showtimes_sample.html`)는 실제 CGV 응답이 아니라
합성 HTML입니다. 파서 로직을 고정하는 용도이고, 실제 사이트 동작을 보장하지는 않습니다.
실제 응답을 받으면 그걸로 교체하는 편이 훨씬 낫습니다.

```
cgv_watch/
├── client.py     상영시간표 조회 + 파싱
├── watcher.py    폴링 루프 · 엣지 트리거 · 상태 관리
├── booker.py     Playwright 자동화 (결제 직전까지)
├── config.py     YAML + ${ENV} 설정
├── models.py     Showtime 모델 · 예매 딥링크
└── notifiers/    telegram · desktop · console
```
