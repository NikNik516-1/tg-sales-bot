FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY services/ai-worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared/ ./
COPY services/ai-worker/ ./
CMD ["python", "main.py"]
