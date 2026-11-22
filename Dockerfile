# Recipe for the app's image: a small Linux system with Python, the app's
# dependencies and the app code. `docker compose up` builds it automatically.
FROM python:3.14-slim

# Print logs straight away (so the generated admin password shows up in
# `docker compose logs`) and don't write .pyc files into the image.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TRACKER_DB=/data/tracker.db

WORKDIR /code

# Dependencies first: Docker caches this layer, so code-only changes rebuild in seconds.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

# Run as a normal user instead of root. /data is where the database lives;
# compose mounts a volume there so the data survives container rebuilds.
RUN useradd --create-home appuser \
    && mkdir /data \
    && chown appuser /data
USER appuser
VOLUME /data

EXPOSE 8000

# 0.0.0.0 = listen on every network interface inside the container, which is
# needed for Docker's port mapping to reach it. compose.yaml still only
# publishes the port on this machine's localhost.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
