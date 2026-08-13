# 서버 상시 감시용 이미지 — 알림 전용입니다.
# 브라우저 자동 예매(booking.enabled)는 화면이 있는 로컬 PC에서 쓰세요.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Seoul

WORKDIR /app

# playwright 는 서버 이미지에서 제외 (알림 전용)
COPY requirements.txt .
RUN grep -v '^playwright' requirements.txt > /tmp/req.txt \
    && pip install --no-cache-dir -r /tmp/req.txt

COPY cgv_watch ./cgv_watch

# config.yaml 과 .env 는 볼륨으로 마운트
CMD ["python", "-m", "cgv_watch", "watch", "-c", "/app/config.yaml"]
