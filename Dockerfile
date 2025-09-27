FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 TZ=Asia/Tokyo
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV DB_PATH=/data/skeddy.db

CMD ["python", "skeddybot.py"]
