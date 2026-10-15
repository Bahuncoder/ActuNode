# actunode test in a container (D-49): docker compose run --rm runner test scenarios/
FROM python:3.12-slim
WORKDIR /src
COPY pyproject.toml README.md requirements.txt ./
# Dependencies from the bounded requirements file, then the package itself (build tool pinned to a range).
RUN pip install --no-cache-dir -r requirements.txt "setuptools>=77,<85"
COPY actunode ./actunode
RUN pip install --no-cache-dir --no-deps --no-build-isolation . && rm -rf /src \
    && useradd --uid 1000 --create-home runner
USER runner
WORKDIR /work
ENTRYPOINT ["actunode"]
CMD ["--help"]
