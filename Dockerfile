# ---- Builder Stage ----
FROM python:3.10-slim as builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app-build

# Copiar requirements.txt para aprovechar el cache de Docker
COPY requirements.txt requirements.txt

# Crear y activar un entorno virtual, luego instalar dependencias
RUN python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# ---- Final Stage ----
FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

ARG APP_USER_UID=1000
ARG APP_USER_GID=1000

# Instalar dependencias mínimas de runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Crear un usuario no root
RUN groupadd --gid ${APP_USER_GID} appgroup && \
    useradd --uid ${APP_USER_UID} --gid ${APP_USER_GID} --create-home --shell /sbin/nologin appuser

# Copiar el entorno virtual del builder stage
COPY --from=builder --chown=appuser:appgroup /opt/venv /opt/venv

WORKDIR /app

# ========================================================================
# --- MODIFICACIÓN CLAVE ---
# Copiar todos los archivos de la aplicación necesarios
# ========================================================================
COPY --chown=appuser:appgroup app.py config.py ./
COPY --chown=appuser:appgroup src/ ./src/
# ========================================================================

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Comando para ejecutar la aplicación
CMD ["sh", "-c", "/opt/venv/bin/gunicorn app:app --bind \"0.0.0.0:${PORT}\" --workers 4 --timeout 120 --access-logfile - --error-logfile -"]