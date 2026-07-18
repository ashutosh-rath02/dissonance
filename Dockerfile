FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
COPY dissonance dissonance
COPY web web
COPY evals evals
COPY configs configs

RUN pip install --no-cache-dir -e .

EXPOSE 8000
CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000"]
