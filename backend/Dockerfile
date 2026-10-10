FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Run as a non-root user. Compose overrides the uid/gid to match the host user so that
# session files written to the mounted ./sessions directory belong to them.
RUN useradd --uid 1000 --no-create-home --shell /usr/sbin/nologin actunode \
    && mkdir -p /app/sessions && chown actunode /app/sessions
USER actunode

EXPOSE 8000
# Graceful-shutdown limit below Docker's 10 s stop timeout, so the app's own shutdown
# (closing a recording with its end record, MQTT disconnect) always runs before a SIGKILL.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "5"]
