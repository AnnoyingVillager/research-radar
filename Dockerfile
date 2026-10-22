FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.10.4 \
    && groupadd --gid 10001 radar \
    && useradd --uid 10001 --gid radar --create-home radar

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev

COPY app ./app
COPY config ./config
COPY docker-entrypoint.sh /usr/local/bin/research-radar-entrypoint

RUN mkdir -p /app/data /app/logs /app/cache /app/papers \
    && chown -R radar:radar /app \
    && chmod +x /usr/local/bin/research-radar-entrypoint

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

ENTRYPOINT ["research-radar-entrypoint"]
CMD ["python", "-m", "app.run"]

