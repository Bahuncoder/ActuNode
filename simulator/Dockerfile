FROM python:3.14-slim

WORKDIR /app
COPY simulator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY simulator ./simulator

# The simulator needs no privileges.
RUN useradd --uid 1000 --no-create-home --shell /usr/sbin/nologin actunode
USER actunode

CMD ["python", "-m", "simulator"]
