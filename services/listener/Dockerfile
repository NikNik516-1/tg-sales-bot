FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY services/listener/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# shared/ копируется первым, сервис поверх — локальные файлы побеждают
COPY shared/ ./
COPY services/listener/ ./
CMD ["python", "main.py"]
