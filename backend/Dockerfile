FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir \
    "fastapi>=0.110" \
    "uvicorn[standard]>=0.27" \
    "pydantic>=2.6" \
    "pydantic-settings>=2.2" \
    "asyncpg>=0.29" \
    "structlog>=24.1" \
    "python-json-logger>=2.0" \
    "httpx>=0.27" \
    "pyjwt[crypto]>=2.8" \
    "cryptography>=42.0" \
    "argon2-cffi>=23.1"

# Stage dev : bind-mount du code, reload activé
FROM base AS dev
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--reload", "--reload-dir", "/app/app"]

# Stage prod : code embarqué, user non-root
FROM base AS prod
RUN useradd -r -u 1001 -m harpocrate
COPY app ./app
COPY migrations ./migrations
USER harpocrate
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
