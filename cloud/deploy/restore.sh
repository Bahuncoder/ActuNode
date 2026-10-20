#!/usr/bin/env bash
# Restore a backup made by backup.sh onto this host (D-61). Stops the labs and the control plane, replaces the control
# database, the labs' secrets volumes, the workspace folders and the server's secrets; what was there is kept aside
# (folders) or overwritten (volumes). Starts nothing: run prod-up.sh (or local-up.sh) afterwards.
# Usage: ACTUNODE_RESTORE_CONFIRM=yes restore.sh <archive> [root]
set -euo pipefail
archive="${1:?usage: restore.sh <archive> [root]}"
if [ -n "${2:-}" ]; then root="$2"
elif [ -d /srv/actunode ]; then root=/srv/actunode
else root="${ACTUNODE_CLOUD_HOME:-$HOME/.actunode-cloud}"; fi
[ -f "$archive" ] || { echo "no such archive: $archive" >&2; exit 1; }
if [ "${ACTUNODE_RESTORE_CONFIRM:-}" != yes ]; then
  echo "Would restore $archive into $root: stop all ws-* labs and actunode-cloud, replace the control database,"
  echo "the ws-*_secrets volumes, $root/data/workspaces, secrets, certs and config.env (old folders kept aside)."
  echo "Contents:"; tar -tzf "$archive" | head -40
  echo "Set ACTUNODE_RESTORE_CONFIRM=yes to do it."; exit 1
fi
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
tar -C "$tmp" -xzpf "$archive"
[ -f "$tmp/cloud.sqlite3" ] || { echo "not an ActuNode backup (no cloud.sqlite3)" >&2; exit 1; }
stamp="$(date -u +%Y%m%dT%H%M%SZ)"

for p in $(docker compose ls -a -q | grep '^ws-' || true); do
  echo "stopping $p"
  if ! docker compose -p "$p" down 2>/dev/null; then
    ids="$(docker ps -q --filter "label=com.docker.compose.project=$p")"
    [ -z "$ids" ] || docker stop $ids >/dev/null
  fi
done
echo "stopping actunode-cloud"
if ! docker compose -p actunode-cloud down 2>/dev/null; then
  ids="$(docker ps -q --filter label=com.docker.compose.project=actunode-cloud)"
  [ -z "$ids" ] || docker stop $ids >/dev/null
fi

echo "restoring the control database"
docker volume create actunode-cloud_cloud-data >/dev/null
docker run --rm -v actunode-cloud_cloud-data:/v -v "$tmp":/in:ro alpine sh -c \
  'rm -f /v/cloud.sqlite3 /v/cloud.sqlite3-wal /v/cloud.sqlite3-shm && cp /in/cloud.sqlite3 /v/cloud.sqlite3 && chown 1001 /v /v/cloud.sqlite3 && chmod 600 /v/cloud.sqlite3'  # the control plane (uid 1001) writes the journal next to it

for t in "$tmp"/volumes/*.tar; do
  [ -e "$t" ] || continue
  vol="$(basename "$t" .tar)"
  case "$vol" in ws-*_secrets) ;; *) echo "skipping unexpected $vol"; continue ;; esac
  echo "restoring volume $vol"
  docker volume create "$vol" >/dev/null
  docker run --rm -v "$vol":/v -v "$tmp/volumes":/in:ro alpine sh -c "find /v -mindepth 1 -delete && tar -C /v -xpf /in/$vol.tar"
done

aside() {  # aside <source in the extracted backup> <destination under root>: old one moved away, new one copied in
  [ -e "$1" ] || return 0
  mkdir -p "$(dirname "$2")"
  [ ! -e "$2" ] || mv "$2" "$2.before-restore-$stamp"
  cp -a "$1" "$2"; echo "restored $2"
}
aside "$tmp/data/workspaces" "$root/data/workspaces"
aside "$tmp/secrets" "$root/secrets"
aside "$tmp/certs" "$root/certs"
aside "$tmp/config.env" "$root/config.env"
echo "Restored. Nothing is started: now run prod-up.sh (or local-up.sh)."
