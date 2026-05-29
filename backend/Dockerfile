FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Deps layer — cached until pyproject.toml changes
# Note: first build takes ~5-10 min (docling pulls torch + ML deps)
COPY pyproject.toml ./
RUN uv sync --no-dev --no-install-project

COPY src/ ./src/
RUN uv sync --no-dev

RUN mkdir -p /data/raw_pdfs /data/processed /data/artifacts

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "docifer_backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
