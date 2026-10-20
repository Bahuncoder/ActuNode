#!/usr/bin/env bash
# Start (or update) ActuNode Cloud on the server (D-61). Reads /srv/actunode/config.env and the secrets in
# /srv/actunode/secrets (docs/HOSTED_DEPLOY.md lists them). Safe to run again after changing either.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
root=/srv/actunode
set -a; . "$root/config.env"; set +a
: "${ACTUNODE_CLOUD_DOMAIN:?}" "${ACTUNODE_RELEASE:?}" "${ACME_EMAIL:?set ACME_EMAIL in config.env}"
: "${ACTUNODE_GITHUB_CLIENT_ID:?}" "${ACTUNODE_GOOGLE_CLIENT_ID:-}"
export ACTUNODE_DATA_DIR="$root/data" ACTUNODE_CLOUD_SECRETS="$root/secrets" ACTUNODE_CERTS_DIR="$root/secrets"
export ACTUNODE_IMAGES=ghcr.io/bahuncoder/actunode ACTUNODE_VERSION="${ACTUNODE_RELEASE#v}" ACTUNODE_CLOUD_DEV_LOGIN=0
for secret in secret provisioner-token hetzner-dns-token github-client-secret; do
  [ -s "$root/secrets/$secret" ] || { echo "missing $root/secrets/$secret (docs/HOSTED_DEPLOY.md)" >&2; exit 1; }
done
[ -e "$root/secrets/google-client-secret" ] || : > "$root/secrets/google-client-secret"  # Google is optional
touch "$root/secrets/allowlist"
# Readable by root (edge, provisioner) and the control plane's user (uid 1001) only; each container mounts just the
# files it uses (compose.yml, compose.prod.yml).
chown -R root:1001 "$root/secrets" && chmod 0640 "$root/secrets"/* && chmod 0750 "$root/secrets"

install -d -m 0755 "$root/data/lab/mosquitto" "$root/data/lab/tls" "$root/data/workspaces"
install -m 0644 "$repo/mosquitto/init-secrets.sh" "$root/data/lab/mosquitto/init-secrets.sh"
install -m 0644 "$repo/mosquitto/config/acl" "$root/data/lab/mosquitto/acl"
install -m 0644 "$here/../provisioner/lab/mosquitto-hosted.conf" "$root/data/lab/mosquitto/mosquitto-hosted.conf"
install -m 0644 "$repo/tls/init-certs.sh" "$root/data/lab/tls/init-certs.sh"
envsubst '$ACME_EMAIL' < "$here/traefik.prod.yml" > "$root/traefik.yml"  # the ACME email filled in
export ACTUNODE_TRAEFIK_CONFIG="$root/traefik.yml"

for image in backend simulator frontend; do docker pull "$ACTUNODE_IMAGES-$image:$ACTUNODE_VERSION"; done
cd "$here"
docker compose -f compose.yml -f compose.prod.yml up -d --build --wait
# Every running lab is recreated on the new images (a short interruption per lab); stopped labs upgrade at their next wake.
docker compose -f compose.yml -f compose.prod.yml exec -T provisioner /venv/bin/python -m provisioner.app upgrade
# Daily backup (03:30 UTC) of the database, lab secrets, workspace folders and settings: backup.sh, docs/HOSTED_DEPLOY.md.
if [ "$(id -u)" = 0 ] && [ -d /run/systemd/system ]; then
  cat > /etc/systemd/system/actunode-backup.service <<UNIT
[Unit]
Description=ActuNode Cloud backup

[Service]
Type=oneshot
EnvironmentFile=$root/config.env
ExecStart=$here/backup.sh
UNIT
  cat > /etc/systemd/system/actunode-backup.timer <<'UNIT'
[Unit]
Description=Daily ActuNode Cloud backup

[Timer]
OnCalendar=*-*-* 03:30:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
UNIT
  systemctl daemon-reload && systemctl enable --now actunode-backup.timer
  # Health check every 5 minutes, alerts to ACTUNODE_ALERT_WEBHOOK (config.env): healthcheck.sh, docs/HOSTED_DEPLOY.md.
  cat > /etc/systemd/system/actunode-healthcheck.service <<UNIT
[Unit]
Description=ActuNode Cloud health check

[Service]
Type=oneshot
EnvironmentFile=$root/config.env
ExecStart=$here/healthcheck.sh --quiet
UNIT
  cat > /etc/systemd/system/actunode-healthcheck.timer <<'UNIT'
[Unit]
Description=ActuNode Cloud health check every 5 minutes

[Timer]
OnCalendar=*:0/5
Persistent=false

[Install]
WantedBy=timers.target
UNIT
  systemctl daemon-reload && systemctl enable --now actunode-healthcheck.timer
else
  echo "backup and health check timers not installed (needs root and systemd); run $here/backup.sh and $here/healthcheck.sh yourself"
fi
echo "ActuNode Cloud is running: https://app.$ACTUNODE_CLOUD_DOMAIN"
