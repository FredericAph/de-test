FROM python:3.12-slim

WORKDIR /app

# pandas/numpy ship manylinux wheels for python:3.12-slim, so no extra system deps needed
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# application code
COPY app/ ./app/

# test suite (so `pytest` can be run inside the container)
COPY tests/ ./tests/
COPY pyproject.toml ./

# input data files
COPY data/ ./data/

# directory for the DuckDB database file (created automatically on startup)
RUN mkdir -p /app/db

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
