# actunode test in a container (D-49): docker compose run --rm runner test scenarios/
FROM python:3.12-slim
WORKDIR /src
COPY pyproject.toml README.md requirements.txt ./
COPY actunode ./actunode
RUN pip install --no-cache-dir . && rm -rf /src \
    && useradd --uid 1000 --create-home runner
USER runner
WORKDIR /work
ENTRYPOINT ["actunode"]
CMD ["--help"]
