FROM python:3.12-slim

WORKDIR /app

# подписки хранятся в /data — смонтируй сюда volume, чтобы они переживали рестарты
ENV DATA_DIR=/data
RUN mkdir -p /data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

CMD ["python", "bot.py"]
