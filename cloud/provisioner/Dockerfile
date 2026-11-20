# The provisioner (D-61): docker CLI + compose, talking to Docker only through a restricted API proxy (DOCKER_HOST).
# Trivy AVD-DS-0002 (no USER) is accepted here only (see .trivyignore): root is needed to chown workspace files;
# compose drops all caps but CHOWN, FOWNER, DAC_OVERRIDE, sets no-new-privileges; no Docker socket, only a proxy.
FROM docker:29.10.0-cli
# buildx is removed: the provisioner never builds images and the Docker proxy refuses builds.
# pip and setuptools are removed after install: the provisioner never installs packages at runtime and they carried
# vendored CVEs.
RUN apk upgrade --no-cache \
    && rm -f /usr/local/libexec/docker/cli-plugins/docker-buildx \
    && apk add --no-cache python3 \
    && python3 -m venv /venv \
    && /venv/bin/pip install --no-cache-dir "fastapi==0.143.0" "uvicorn>=0.30,<1" \
    && /venv/bin/pip uninstall -y pip setuptools
WORKDIR /srv
COPY provisioner ./provisioner
EXPOSE 8100
# Root inside: it hands each workspace's files to the lab's user (chown). It has no Docker socket, only the proxy.
CMD ["/venv/bin/uvicorn", "provisioner.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8100"]
