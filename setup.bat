@echo off
REM Windows 최초 설치 스크립트.  탐색기에서 더블클릭하거나, cmd 에서: setup.bat
chcp 65001 >nul
cd /d "%~dp0"
echo ════════ CGV 빈자리 감시 설치 ════════
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo [X] 파이썬이 없습니다.
  echo     https://www.python.org/downloads/ 에서 설치하세요.
  echo     설치 화면에서 "Add Python to PATH" 를 반드시 체크하세요.
  pause & exit /b 1
)
for /f "delims=" %%v in ('python --version') do echo [O] 파이썬: %%v

if not exist .venv (
  echo -^> 가상환경 만드는 중...
  python -m venv .venv || (echo [X] 가상환경 생성 실패 & pause & exit /b 1)
)
call .venv\Scripts\activate.bat

echo -^> 패키지 설치 중... (1~2분)
python -m pip install -q --upgrade pip >nul 2>&1
python -m pip install -q -r requirements.txt || (echo [X] 패키지 설치 실패. 인터넷 연결 확인 & pause & exit /b 1)
echo [O] 패키지 설치 완료

echo -^> 자동 예매용 브라우저 준비 중... (수백 MB, 몇 분 걸릴 수 있음)
playwright install chromium >nul 2>&1
if errorlevel 1 (
  echo [!] 브라우저 자동 설치 실패 - 알림 기능은 그대로 씁니다.
  echo     나중에 다시: .venv\Scripts\activate ^&^& playwright install chromium
) else (
  echo [O] 브라우저 준비 완료
)

if not exist config.yaml (
  copy /y presets\odyssey-yongsan-20260814.yaml config.yaml >nul
  echo [O] config.yaml 생성 ^(8/14 용산 IMAX 11시 오디세이 감시 설정^)
) else (
  echo [O] config.yaml 이미 있음 - 그대로 둡니다
)

if not exist .env (
  echo.
  echo ──── 텔레그램 알림 설정 ^(폰으로 알림 받기^) ────
  echo   1^) 텔레그램에서 @BotFather 검색 -^> /newbot -^> 토큰 복사
  echo   2^) 만든 봇과 대화 시작 -^> 아무 메시지나 전송
  echo   3^) https://api.telegram.org/bot^<토큰^>/getUpdates 접속 -^> chat id 확인
  echo.
  set /p TOKEN="봇 토큰 (건너뛰려면 그냥 Enter): "
  set /p CHATID="chat id  (건너뛰려면 그냥 Enter): "
  (echo TELEGRAM_BOT_TOKEN=%TOKEN%& echo TELEGRAM_CHAT_ID=%CHATID%) > .env
  echo [O] .env 저장
) else (
  echo [O] .env 이미 있음 - 그대로 둡니다
)

echo.
echo ════════ 설치 끝. 이제 아래를 순서대로 ════════
echo.
echo   .venv\Scripts\activate                 :: 창을 새로 열 때마다 매번
echo   python -m cgv_watch check --notify     :: (1) 설정 점검
echo   python -m cgv_watch login              :: (2) 브라우저에 직접 CGV 로그인
echo   python -m cgv_watch watch              :: (3) 감시 시작 - 창을 켜둔 채로
echo.
pause
