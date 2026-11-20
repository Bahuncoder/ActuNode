FROM python:3.15-slim
# Debian's security fixes reach the python base image days later (D-64): install them at build time.
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

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
# --ws-max-size: the live feed accepts no client data (audit W5).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "5", "--ws-max-size", "4096"]
