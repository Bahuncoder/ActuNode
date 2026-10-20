#!/usr/bin/env bash
# Health check for ActuNode Cloud (D-61): one line per check ("ok <name>" / "FAIL <name>: <detail>"), exit 1 on any
# failure, alert to ACTUNODE_ALERT_WEBHOOK when the set of failures changes (and daily while it persists).
# Usage: healthcheck.sh [--quiet] [root]   (default /srv/actunode if it exists, else ~/.actunode-cloud)
# See docs/HOSTED_DEPLOY.md.
set -uo pipefail
quiet=0; root=""
for a in "$@"; do case "$a" in --quiet) quiet=1 ;; *) root="$a" ;; esac; done
if [ -z "$root" ]; then
  if [ -d /srv/actunode ]; then root=/srv/actunode; else root="${ACTUNODE_CLOUD_HOME:-$HOME/.actunode-cloud}"; fi
fi
[ -f "$root/config.env" ] && { set -a; . "$root/config.env"; set +a; }
domain="${ACTUNODE_CLOUD_DOMAIN:-}"; port="${ACTUNODE_CLOUD_PUBLIC_PORT:-}"
[ -n "$domain" ] || { echo "FAIL config: ACTUNODE_CLOUD_DOMAIN is not set"; exit 1; }
host="app.$domain"; tlsport="${port#:}"; tlsport="${tlsport:-443}"
ca=""; [ -f "$root/certs/ca.crt" ] && ca="$root/certs/ca.crt"
out=""; failed=()
check() {  # check <name> <detail>: an empty detail is a pass
  if [ -z "$2" ]; then out+="ok $1"$'\n'; else out+="FAIL $1: $2"$'\n'; failed+=("$1"); fi
}

if curl -fsS -m 10 ${ca:+--cacert "$ca"} -o /dev/null "https://$host$port/healthz" 2>/dev/null; then check app ""
else check app "https://$host$port/healthz did not answer"; fi

if echo | openssl s_client ${ca:+-CAfile "$ca"} -verify_return_error -servername "$host" -connect "$host:$tlsport" 2>/dev/null \
   | openssl x509 -noout -checkend 1209600 >/dev/null 2>&1; then check edge-tls ""
else check edge-tls "certificate for $host is invalid, unreachable or expires within 14 days"; fi

for pair in control-plane:actunode-control-plane provisioner:actunode-provisioner; do
  s="$(docker inspect -f '{{.State.Health.Status}}' "${pair#*:}" 2>&1 | head -n1)"
  if [ "$s" = healthy ]; then check "${pair%%:*}" ""; else check "${pair%%:*}" "${s:-no such container}"; fi
done
s="$(docker inspect -f '{{.State.Status}}' actunode-edge 2>&1 | head -n1)"
if [ "$s" = running ]; then check edge ""; else check edge "${s:-no such container}"; fi

pct="$(df --output=pcent "$root" 2>/dev/null | tail -n1 | tr -dc 0-9)"; lim="${ACTUNODE_DISK_ALERT_PCT:-85}"
if [ -z "$pct" ]; then check disk "cannot read the use of $root"
elif [ "$pct" -ge "$lim" ]; then check disk "$pct% used (limit $lim%)"; else check disk ""; fi

if [ -d "$root/backups" ]; then
  newest="$(ls -1 "$root/backups"/actunode-*.tar.gz 2>/dev/null | sort | tail -n1)"; maxh="${ACTUNODE_BACKUP_MAX_AGE_H:-36}"
  if [ -z "$newest" ]; then check backup "no archive in $root/backups"
  elif [ $(( $(date +%s) - $(stat -c %Y "$newest") )) -gt $((maxh * 3600)) ]; then
    check backup "newest archive $(basename "$newest") is older than $maxh h"
  else check backup ""; fi
else out+="ok backup (none expected yet)"$'\n'; fi

bad=""
for p in $(docker compose ls -q 2>/dev/null | grep '^ws-'); do
  while read -r name state status; do
    case "$state$status" in *unhealthy*|exited*|restarting*|dead*|*"(unhealthy)"*) bad+=" $name($state)" ;; esac
  done < <(docker ps --filter "label=com.docker.compose.project=$p" --format '{{.Names}} {{.State}} {{.Status}}')
done
check labs "${bad# }"

failtxt="$(printf '%s\n' "${failed[@]}")"; [ ${#failed[@]} = 0 ] && failtxt=""
if [ "$quiet" = 1 ]; then printf '%s' "$out" | grep '^FAIL' || true; else printf '%s' "$out"; fi

# Alert when the set of failures changes, or once a day while it persists. State: failing names, then "lastalert <epoch>".
state="$root/healthcheck.state"; now="$(date +%s)"
prev="$(grep -v '^lastalert ' "$state" 2>/dev/null)"; last="$(sed -n 's/^lastalert //p' "$state" 2>/dev/null)"
if [ -n "${ACTUNODE_ALERT_WEBHOOK:-}" ] && { [ "$failtxt" != "$prev" ] || { [ -n "$failtxt" ] && [ $((now - ${last:-0})) -ge 86400 ]; }; }; then
  if [ -n "$failtxt" ]; then msg="$(hostname): FAILING $(printf '%s' "$out" | grep '^FAIL' | tr '\n' ';')"
  else msg="$(hostname): all ActuNode Cloud checks ok again"; fi
  body="$(printf '%s' "$msg" | sed 's/\\/\\\\/g; s/"/\\"/g')"
  if printf '{"text": "%s", "content": "%s"}' "$body" "$body" \
     | curl -fsS -m 10 -H 'Content-Type: application/json' --data @- "$ACTUNODE_ALERT_WEBHOOK" >/dev/null 2>&1; then last="$now"
  else echo "alert to the webhook FAILED" >&2; fi
fi
{ [ -n "$failtxt" ] && echo "$failtxt"; [ -n "${last:-}" ] && echo "lastalert $last"; } > "$state" 2>/dev/null
[ ${#failed[@]} = 0 ]
