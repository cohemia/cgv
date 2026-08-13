#!/usr/bin/env bash
# macOS / Linux 최초 설치 스크립트.  실행:  bash setup.sh
set -u

cd "$(dirname "$0")"
echo "════════ CGV 빈자리 감시 설치 ════════"
echo

# 1. 파이썬 확인 -------------------------------------------------------------
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info>=(3,9) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "❌ 파이썬 3.9 이상이 없습니다."
  echo "   macOS:  brew install python3   (또는 https://www.python.org/downloads/ 에서 설치)"
  exit 1
fi
echo "✅ 파이썬: $($PY --version)"

# 2. 가상환경 + 패키지 --------------------------------------------------------
if [ ! -d .venv ]; then
  echo "→ 가상환경 만드는 중..."
  "$PY" -m venv .venv || { echo "❌ 가상환경 생성 실패"; exit 1; }
fi
# shellcheck disable=SC1091
source .venv/bin/activate
echo "→ 패키지 설치 중... (1~2분)"
pip install -q --upgrade pip >/dev/null 2>&1
if ! pip install -q -r requirements.txt; then
  echo "❌ 패키지 설치 실패. 인터넷 연결을 확인하세요."
  exit 1
fi
echo "✅ 패키지 설치 완료"

# 3. 브라우저 ----------------------------------------------------------------
echo "→ 자동 예매용 브라우저 준비 중... (수백 MB, 몇 분 걸릴 수 있음)"
if playwright install chromium >/dev/null 2>&1; then
  echo "✅ 브라우저 준비 완료"
else
  echo "⚠️  브라우저 자동 설치 실패 — 알림 기능은 그대로 씁니다."
  echo "   자동 예매까지 쓰려면 나중에 다시:  source .venv/bin/activate && playwright install chromium"
fi

# 4. 설정 파일 ----------------------------------------------------------------
if [ ! -f config.yaml ]; then
  cp presets/odyssey-yongsan-20260814.yaml config.yaml
  echo "✅ config.yaml 생성 (8/14 용산 IMAX 11시 오디세이 감시 설정)"
else
  echo "✅ config.yaml 이미 있음 — 그대로 둡니다"
fi

# 5. 텔레그램 -----------------------------------------------------------------
if [ ! -f .env ]; then
  echo
  echo "──── 텔레그램 알림 설정 (폰으로 알림 받기) ────"
  echo "  1) 텔레그램에서 @BotFather 검색 → /newbot → 이름 아무거나 → 토큰 복사"
  echo "  2) 방금 만든 봇을 검색해서 대화 시작 → 아무 메시지나 전송"
  echo "  3) 브라우저에서 https://api.telegram.org/bot<토큰>/getUpdates 접속"
  echo "     → \"chat\":{\"id\":123456789 에서 그 숫자가 chat id"
  echo
  printf "봇 토큰 (건너뛰려면 그냥 Enter): "; read -r TOKEN
  printf "chat id  (건너뛰려면 그냥 Enter): "; read -r CHATID
  { echo "TELEGRAM_BOT_TOKEN=$TOKEN"; echo "TELEGRAM_CHAT_ID=$CHATID"; } > .env
  if [ -n "$TOKEN" ] && [ -n "$CHATID" ]; then
    echo "✅ 텔레그램 설정 저장"
  else
    echo "⚠️  건너뜀 — 나중에 .env 파일에 채우면 됩니다 (지금은 PC 알림만 옵니다)"
  fi
else
  echo "✅ .env 이미 있음 — 그대로 둡니다"
fi

echo
echo "════════ 설치 끝. 이제 아래를 순서대로 ════════"
echo
echo "  source .venv/bin/activate            # 창을 새로 열 때마다 매번"
echo "  python -m cgv_watch check --notify   # ① 설정 점검 (전부 ✅ 나와야 함)"
echo "  python -m cgv_watch login            # ② 브라우저에 직접 CGV 로그인"
if [ "$(uname)" = "Darwin" ]; then
  echo "  caffeinate -i python -m cgv_watch watch   # ③ 감시 시작"
  echo
  echo "  ⚠️  맥은 잠자기에 들어가면 감시가 멈춥니다."
  echo "     위처럼 caffeinate -i 를 앞에 붙여야 밤새 돌아갑니다."
  echo "     덮개를 닫으면 그래도 잠드니, 덮개는 열어두세요."
else
  echo "  python -m cgv_watch watch            # ③ 감시 시작 — 창을 켜둔 채로"
fi
echo
