FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY services/bot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared/ ./
COPY services/bot/ ./
CMD ["python", "main.py"]
