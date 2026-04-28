FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# curl-cffi may need to build native bits if no wheel matches; keep toolchain available.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libcurl4-openssl-dev \
        libssl-dev \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy project metadata + create a stub package so dependency install can run
# before the real source is added. This keeps the slow pip layer cached when
# only application code changes.
COPY pyproject.toml ./
RUN mkdir -p api && touch api/__init__.py \
    && pip install --upgrade pip \
    && pip install -e .

# Overlay the real source; editable install resolves imports here.
COPY . ./api/

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
