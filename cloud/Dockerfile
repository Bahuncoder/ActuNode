# ActuNode Cloud control plane (D-61).
FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN useradd --uid 1001 --no-create-home --shell /usr/sbin/nologin cloud && mkdir -p /data && chown cloud /data
USER cloud
EXPOSE 8000
# Behind the edge only (no published port): its X-Forwarded-* headers are believed.
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
