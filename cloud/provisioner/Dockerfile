# The provisioner (D-61): docker CLI + compose, talking to Docker only through a restricted API proxy (DOCKER_HOST).
FROM docker:28-cli
RUN apk add --no-cache python3 \
    && python3 -m venv /venv \
    && /venv/bin/pip install --no-cache-dir "fastapi==0.143.0" "uvicorn>=0.30,<1"
WORKDIR /srv
COPY provisioner ./provisioner
EXPOSE 8100
# Root inside: it hands each workspace's files to the lab's user (chown). It has no Docker socket, only the proxy.
CMD ["/venv/bin/uvicorn", "provisioner.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8100"]
