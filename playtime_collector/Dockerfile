FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY playtime ./playtime
# Web UI pages served by the FastAPI app (dashboard / settings / people).
COPY templates ./templates
# The add-on's own icon, served at GET /icon as the web UI favicon.
COPY icon.png ./icon.png

# Home Assistant provides options via /data/options.json and the data volume.
CMD ["python", "-m", "playtime"]
