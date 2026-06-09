FROM python:3.12-slim

# chromadb (hnswlib) needs C++ compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

# Install deps first so this layer is cached when only app code changes
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --frozen 2>/dev/null || uv sync --no-dev

# Copy app code (includes chroma_versions/v5 knowledge base snapshot)
COPY . .

# Ensure runtime data directories exist
RUN mkdir -p data/uploads data/search_outputs data/generated_forms

EXPOSE 8000

# Run alembic migration then start uvicorn
# run_server.py is a Windows-specific event loop workaround; use uvicorn directly on Linux
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000"]
