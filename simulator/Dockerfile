FROM python:3.15-slim
# Debian's security fixes reach the python base image days later (D-64): install them at build time.
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY simulator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY simulator ./simulator

# The simulator needs no privileges.
RUN useradd --uid 1000 --no-create-home --shell /usr/sbin/nologin actunode
USER actunode

CMD ["python", "-m", "simulator"]
