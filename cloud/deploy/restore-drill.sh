#!/usr/bin/env bash
# Restore drill, local only: prove that a backup brings the hosted service back (D-61). Run after local-up.sh and
# local-check.sh (workspace alpha with the robot login AcmeRobotics.amr-7). DESTROYS the local stack's data, then restores it.
# Pass ACTUNODE_IDLE_STOP_S etc. in the environment as for local-up.sh.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
base="${ACTUNODE_CLOUD_HOME:-$HOME/.actunode-cloud}"
case "$(cd "$base" && pwd -P)" in "$HOME"/*) ;; *) echo "refusing: $base is not under \$HOME (local only)" >&2; exit 1 ;; esac
CA="$base/certs/ca.crt" APP="https://app.actunode.localhost:9443"
# compose.yml needs these to be parsed at all (as local-up.sh exports them).
export ACTUNODE_DATA_DIR="$base/data" ACTUNODE_CERTS_DIR="$base/certs" ACTUNODE_CLOUD_SECRETS="$base/secrets"
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
fail=0
check() { if [ "$2" = "$3" ]; then echo "ok    $1"; else echo "FAIL  $1: got '$2', expected '$3'"; fail=1; fi; }
browser() { curl -s --cacert "$CA" -b "$work/$1" -c "$work/$1" "${@:2}"; }
status() { browser "$1" -o /dev/null -w '%{http_code}' "${@:2}"; }
post() { browser "$1" -o /dev/null -w '%{http_code}' -H "Origin: $APP" "${@:2}"; }
mqtt() {  # mqtt <workspace> <user> <password> <topic>
  docker run --rm --network host --add-host "$1.actunode.localhost:127.0.0.1" -v "$CA:/ca.crt:ro" eclipse-mosquitto:2 \
    mosquitto_pub -h "$1.actunode.localhost" -p 18883 --cafile /ca.crt -u "$2" -P "$3" -t "$4" -m '{}' -q 1 \
    >/dev/null 2>&1 && echo accepted || echo refused
}

compose="docker compose -p ws-alpha -f $base/data/workspaces/alpha/compose.yml"
robot_pw="$($compose run --rm --entrypoint cat mqtt-init /secrets/robots/AcmeRobotics.amr-7.password 2>/dev/null || true)"
check "(a) the robot's password was read from the live lab" "$([ -n "$robot_pw" ] && echo yes || echo no)" yes

archive="$("$here/backup.sh" "$base" | sed -n 's/^backup: \(.*\) (.*)$/\1/p')"
check "(b) backup made an archive" "$([ -s "$archive" ] && echo yes || echo no)" yes
[ -s "$archive" ] || exit 1

for f in "$base"/data/workspaces/*/compose.yml; do
  docker compose -p "ws-$(basename "$(dirname "$f")")" -f "$f" down -v >/dev/null 2>&1 || true
done
docker compose -f "$here/compose.yml" down -v >/dev/null 2>&1 || { echo "FAIL  (c) could not take the cloud stack down"; exit 1; }
mv "$base/data/workspaces" "$base/data/workspaces.destroyed-$(date -u +%s)"
check "(c) everything destroyed (control database and lab secrets volumes gone)" "$(docker volume ls -q | grep -c '^actunode-cloud_cloud-data$\|^ws-.*_secrets$' || true)" 0

ACTUNODE_RESTORE_CONFIRM=yes "$here/restore.sh" "$archive" "$base" >/dev/null && r=restored || r=failed
check "(d) restore.sh" "$r" restored
"$here/local-up.sh" >/dev/null 2>&1 && r=up || r=failed
check "(e) local-up.sh starts the restored stack" "$r" up

for _ in $(seq 1 30); do [ "$(status a "$APP/")" = 200 ] && break; sleep 2; done
check "(f) the app answers" "$(status a "$APP/")" 200
check "alice signs in again" "$(post a -d login=alice "$APP/dev/login")" 303
check "the database came back (alpha is listed)" "$(browser a "$APP/workspaces" | grep -o 'alpha' | head -1)" alpha
result=""
for _ in $(seq 1 30); do
  # A transient redirect loop (the edge has not yet seen the new container) makes curl fail: keep polling.
  result="$(browser a -L -o /dev/null -w '%{url_effective}' --max-redirs 6 "$APP/workspaces/alpha/open" || true)"
  [ "$result" = "https://alpha.actunode.localhost:9443/" ] && break; sleep 3
done
check "alpha starts from its restored folder and secrets" "$result" "https://alpha.actunode.localhost:9443/"
check "the robot connects with its OLD password" "$(mqtt alpha AcmeRobotics.amr-7 "$robot_pw" uagv/v2/AcmeRobotics/amr-7/connection)" accepted
check "alpha's recordings folder is back" "$([ -d "$base/data/workspaces/alpha/sessions" ] && echo yes || echo no)" yes
exit $fail
