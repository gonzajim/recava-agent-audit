FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
# No copiar .env en producción; usa variables de entorno de Cloud Run
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "main:app"]
