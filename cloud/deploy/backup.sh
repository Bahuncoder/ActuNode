#!/usr/bin/env bash
# Back up everything ActuNode Cloud needs to run again (D-61): the control database, every lab's secrets volume,
# the workspace folders (recordings), the server's secrets and settings. Needs only docker. See docs/HOSTED_DEPLOY.md.
# Usage: backup.sh [root]   (default /srv/actunode if it exists, else ~/.actunode-cloud)
# ACTUNODE_BACKUP_KEEP=14 archives kept; ACTUNODE_BACKUP_REMOTE=<rclone remote:path> also copies the archive off-site.
set -euo pipefail
umask 077
if [ -n "${1:-}" ]; then root="$1"
elif [ -d /srv/actunode ]; then root=/srv/actunode
else root="${ACTUNODE_CLOUD_HOME:-$HOME/.actunode-cloud}"; fi
keep="${ACTUNODE_BACKUP_KEEP:-14}"
me="$(id -u):$(id -g)"
install -d -m 700 "$root/backups"; chmod 700 "$root/backups"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir "$tmp/volumes"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
archive="$root/backups/actunode-$stamp.tar.gz"

# SQLite online backup: consistent even while the control plane writes (WAL mode).
docker run --rm -e "OWNER=$me" -v actunode-cloud_cloud-data:/data:ro -v "$tmp":/out python:3.12-slim python -c '
import os, sqlite3
src = sqlite3.connect("file:/data/cloud.sqlite3?mode=ro", uri=True)
dst = sqlite3.connect("/out/cloud.sqlite3")
src.backup(dst); dst.close(); src.close()
u, g = os.environ["OWNER"].split(":"); os.chown("/out/cloud.sqlite3", int(u), int(g))'

vols=""
for vol in $(docker volume ls -q --filter name=ws- | grep '_secrets$' || true); do
  docker run --rm -v "$vol":/v:ro -v "$tmp/volumes":/out alpine \
    sh -c "tar -C /v -cf /out/$vol.tar . && chown $me /out/$vol.tar"
  vols="$vols $vol"
done

[ -d "$root/data/workspaces" ] && { mkdir "$tmp/data"; cp -a "$root/data/workspaces" "$tmp/data/workspaces"; }
for item in secrets certs config.env; do [ -e "$root/$item" ] && cp -a "$root/$item" "$tmp/$item"; done

{ echo "date: $(date -u +%FT%TZ)"; echo "host: $(hostname)"; echo "root: $root"
  echo "docker: $(docker --version)"; echo "volumes:${vols:- none}"
  echo "contents:"; (cd "$tmp" && find . -maxdepth 2 -not -name MANIFEST | sort | sed 's/^\.\//  /'); } > "$tmp/MANIFEST"

tar -C "$tmp" -czf "$archive.part" . && mv "$archive.part" "$archive"
chmod 600 "$archive"

# Keep only the newest archives.
ls -1 "$root/backups"/actunode-*.tar.gz | sort -r | tail -n +"$((keep + 1))" | while read -r old; do rm -f -- "$old"; done

echo "backup: $archive ($(du -h "$archive" | cut -f1))"
if [ -n "${ACTUNODE_BACKUP_REMOTE:-}" ]; then
  if command -v rclone >/dev/null; then
    rclone copy "$archive" "$ACTUNODE_BACKUP_REMOTE" || { echo "off-site copy to $ACTUNODE_BACKUP_REMOTE FAILED" >&2; exit 1; }
    echo "copied to $ACTUNODE_BACKUP_REMOTE"
  else echo "ACTUNODE_BACKUP_REMOTE is set but rclone is not installed" >&2; exit 1; fi
fi
