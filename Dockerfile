# syntax=docker/dockerfile:1
FROM node:22-slim AS web
WORKDIR /web
COPY web/ ./
RUN if [ -f package.json ]; then \
      (npm ci || npm install) && npm run build; \
    else mkdir -p dist; fi

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" PORT=8787 LS_DATA_DIR=/app/data
RUN useradd -m -u 1000 app
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY logicscout/ logicscout/
COPY scripts/ scripts/
COPY data/ data/
RUN uv sync --frozen --no-dev
COPY --from=web /web/dist web/dist
RUN mkdir -p data/runs data/library && chown -R app:app /app/data
USER app
EXPOSE 8787
CMD ["sh", "scripts/start.sh"]
