# One image for both services; SERVICE picks which one runs (gateway or reviewer).

FROM python:3.11-slim AS build
WORKDIR /src
COPY pyproject.toml README.md ./
COPY pr_reviewer ./pr_reviewer
RUN pip wheel --no-cache-dir --wheel-dir /wheels ".[aws,otel]"

FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SERVICE=gateway \
    PORT=8000
RUN useradd --create-home --uid 10001 app
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir --no-index /wheels/* && rm -rf /wheels
# The reviewer's SQLite review history lives here (a volume in docker-compose).
RUN mkdir /home/app/data && chown app:app /home/app/data

USER app
WORKDIR /home/app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health', timeout=3)"
# exec so uvicorn gets SIGTERM directly and the worker can finish its current job.
CMD ["sh", "-c", "exec uvicorn pr_reviewer.${SERVICE}.main:create_app --factory --host 0.0.0.0 --port ${PORT} --no-access-log"]
