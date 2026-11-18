# syntax=docker/dockerfile:1
# AgriSense API: FastAPI + simulator + controller + ML scoring.
# Build from the backend folder:  docker build -t agrisense-backend backend

# ---- build: install the package and its dependencies into a virtual environment
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY pyproject.toml ./
COPY agrisense_core ./agrisense_core
COPY app ./app
RUN pip install .

# ---- runtime: only the virtual environment, run as an unprivileged user
FROM python:3.12-slim
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AGRISENSE_ML_DIR=/app/ml
RUN useradd --create-home --uid 10001 agrisense \
    && mkdir -p /app/ml /app/data \
    && chown -R agrisense:agrisense /app
COPY --from=build /opt/venv /opt/venv
WORKDIR /app/data
USER agrisense

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

# One worker: the simulation lives in the process (several workers would run several greenhouses).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
