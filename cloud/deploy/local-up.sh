#!/usr/bin/env bash
# The hosted service on this computer (D-61): https://app.actunode.localhost, workspaces at
# https://<workspace>.actunode.localhost, robots on <workspace>.actunode.localhost:18883 (TLS). Nothing is reachable
# from the network (127.0.0.1). Sign-in is the local development sign-in (no GitHub/Google apps needed).
# Stop: docker compose -f cloud/deploy/compose.yml down (workspace labs: docker compose -p ws-<name> down).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
base="${ACTUNODE_CLOUD_HOME:-$HOME/.actunode-cloud}"
export ACTUNODE_DATA_DIR="$base/data" ACTUNODE_CERTS_DIR="$base/certs" ACTUNODE_CLOUD_SECRETS="$base/secrets"
export ACTUNODE_CLOUD_DOMAIN=actunode.localhost ACTUNODE_CLOUD_DEV_LOGIN=1
export ACTUNODE_IMAGES=actunode ACTUNODE_VERSION=local  # the labs built from this checkout (with SSO)
# Not 80/443: this computer may run another web server there.
export EDGE_BIND=127.0.0.1 EDGE_HTTP_PORT=9080 EDGE_HTTPS_PORT=9443 EDGE_MQTTS_PORT=18883 ACTUNODE_CLOUD_PUBLIC_PORT=:9443
umask 077
mkdir -p "$ACTUNODE_DATA_DIR/lab/mosquitto" "$ACTUNODE_DATA_DIR/lab/tls" "$ACTUNODE_DATA_DIR/workspaces" \
  "$ACTUNODE_CERTS_DIR" "$ACTUNODE_CLOUD_SECRETS"

# The files every workspace lab mounts (host paths).
install -m 0644 "$repo/mosquitto/init-secrets.sh" "$ACTUNODE_DATA_DIR/lab/mosquitto/init-secrets.sh"
install -m 0644 "$repo/mosquitto/config/acl" "$ACTUNODE_DATA_DIR/lab/mosquitto/acl"
install -m 0644 "$here/../provisioner/lab/mosquitto-hosted.conf" "$ACTUNODE_DATA_DIR/lab/mosquitto/mosquitto-hosted.conf"
install -m 0644 "$repo/tls/init-certs.sh" "$ACTUNODE_DATA_DIR/lab/tls/init-certs.sh"
chmod 0755 "$ACTUNODE_DATA_DIR" "$ACTUNODE_DATA_DIR/lab" "$ACTUNODE_DATA_DIR/lab/mosquitto" "$ACTUNODE_DATA_DIR/lab/tls"

# Secrets for the control plane and the provisioner (readable by the control plane's user).
[ -s "$ACTUNODE_CLOUD_SECRETS/secret" ] || openssl rand -hex 32 > "$ACTUNODE_CLOUD_SECRETS/secret"
[ -s "$ACTUNODE_CLOUD_SECRETS/provisioner-token" ] || openssl rand -hex 32 > "$ACTUNODE_CLOUD_SECRETS/provisioner-token"
touch "$ACTUNODE_CLOUD_SECRETS/allowlist"
chmod 0755 "$ACTUNODE_CLOUD_SECRETS" && chmod 0644 "$ACTUNODE_CLOUD_SECRETS"/*

# A local CA and a wildcard certificate for *.actunode.localhost (trust ca.crt in your browser to avoid warnings).
if [ ! -s "$ACTUNODE_CERTS_DIR/wildcard.crt" ]; then
  openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -days 825 -subj "/CN=ActuNode Cloud local CA" \
    -keyout "$ACTUNODE_CERTS_DIR/ca.key" -out "$ACTUNODE_CERTS_DIR/ca.crt" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -addext "nameConstraints=critical,permitted;DNS:actunode.localhost" 2>/dev/null
  openssl req -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -subj "/CN=*.actunode.localhost" \
    -keyout "$ACTUNODE_CERTS_DIR/wildcard.key" -out "$ACTUNODE_CERTS_DIR/wildcard.csr" 2>/dev/null
  printf 'subjectAltName=DNS:*.actunode.localhost,DNS:actunode.localhost\nextendedKeyUsage=serverAuth\n' > "$ACTUNODE_CERTS_DIR/ext"
  openssl x509 -req -in "$ACTUNODE_CERTS_DIR/wildcard.csr" -CA "$ACTUNODE_CERTS_DIR/ca.crt" -CAkey "$ACTUNODE_CERTS_DIR/ca.key" \
    -CAcreateserial -days 397 -extfile "$ACTUNODE_CERTS_DIR/ext" -out "$ACTUNODE_CERTS_DIR/wildcard.crt" 2>/dev/null
  chmod 0644 "$ACTUNODE_CERTS_DIR/wildcard.crt" "$ACTUNODE_CERTS_DIR/wildcard.key" "$ACTUNODE_CERTS_DIR/ca.crt"
  chmod 0755 "$ACTUNODE_CERTS_DIR"
fi

# The lab images with this checkout's code (published 0.3.0 has no single sign-on yet).
docker compose -f "$repo/docker-compose.yml" build backend simulator frontend
docker compose -f "$here/compose.yml" up -d --build --wait

cat <<MSG

ActuNode Cloud (local) is running.
  App:       https://app.actunode.localhost:9443   (sign in with the local development sign-in)
  CA:        $ACTUNODE_CERTS_DIR/ca.crt   (trust it in the browser, or accept the warning)
  Robots:    <workspace>.actunode.localhost:18883 over TLS, with that CA
MSG
