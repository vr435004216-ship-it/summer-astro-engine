FROM python:3.12-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY requirements-lock.txt .
RUN pip wheel --wheel-dir /wheels -r requirements-lock.txt

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SUMMER_DB=/data/forecasts.sqlite
WORKDIR /app
COPY --from=build /wheels /wheels
COPY requirements-lock.txt .
RUN pip install --no-index --find-links=/wheels -r requirements-lock.txt && rm -rf /wheels && useradd --uid 10001 --create-home summer && mkdir /data && chown summer /data
COPY --chown=summer:summer summer_astro ./summer_astro
COPY --chown=summer:summer LICENSE LICENSE-SWISSEPH NOTICE README_AR.md requirements.txt Dockerfile compose.yaml ./
USER summer
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3)"
CMD ["python", "-m", "uvicorn", "summer_astro.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--limit-concurrency", "20", "--timeout-keep-alive", "5"]
