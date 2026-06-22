ARG BUILD_FROM=python:3.12-slim
FROM ${BUILD_FROM}

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY playtime ./playtime

# Home Assistant provides options via /data/options.json and the data volume.
CMD ["python", "-m", "playtime"]
