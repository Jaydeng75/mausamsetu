FROM python:3.12-slim
WORKDIR /app
COPY requirements.lock ./requirements.lock
RUN pip install --no-cache-dir -r requirements.lock
COPY pyproject.toml .
COPY mausam ./mausam
COPY migrations ./migrations
COPY alembic.ini .
RUN pip install --no-cache-dir --no-deps . \
    && useradd -m -u 10001 mausam \
    && mkdir /data && chown mausam:mausam /data
USER mausam
ENV MAUSAM_DATA_DIR=/data PYTHONDONTWRITEBYTECODE=1
EXPOSE 8000
CMD ["uvicorn", "mausam.api:app", "--host", "0.0.0.0", "--port", "8000"]
