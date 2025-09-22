FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml README.md AGENT.md pytest.ini ./
COPY app ./app
COPY tests ./tests
COPY run.sh ./run.sh
COPY .env.example ./.env.example

RUN uv sync --extra dev --extra postgres

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
