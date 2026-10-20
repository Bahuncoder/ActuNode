#!/usr/bin/env bash
# End-to-end check of the hosted service on this computer (after local-up.sh), D-61: sign in, create two
# workspaces (two people), open a lab through single sign-on, connect a robot over MQTT/TLS through the edge, and
# check isolation between workspaces. Leaves the workspaces running; delete them on the app page or with
# `docker compose -p ws-<name> down -v` and remove ~/.actunode-cloud/data/workspaces/<name>.
set -euo pipefail
base="${ACTUNODE_CLOUD_HOME:-$HOME/.actunode-cloud}"
CA="$base/certs/ca.crt" APP="https://app.actunode.localhost:9443"
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
fail=0
check() { if [ "$2" = "$3" ]; then echo "ok    $1"; else echo "FAIL  $1: got '$2', expected '$3'"; fail=1; fi; }
browser() { curl -s --cacert "$CA" -b "$work/$1" -c "$work/$1" "${@:2}"; }
status() { browser "$1" -o /dev/null -w '%{http_code}' "${@:2}"; }
post() { browser "$1" -o /dev/null -w '%{http_code}' -H "Origin: $APP" "${@:2}"; }

for _ in $(seq 1 30); do [ "$(status a "$APP/")" = 200 ] && break; sleep 2; done  # just (re)started
check "app answers over HTTPS" "$(status a "$APP/")" 200
check "alice signs in" "$(post a -d login=alice "$APP/dev/login")" 303
check "bob signs in" "$(post b -d login=bob "$APP/dev/login")" 303
check "alice creates workspace alpha" "$(post a --max-time 600 -d name=Alpha -d slug=alpha "$APP/workspaces")" 303
check "bob creates workspace beta" "$(post b --max-time 600 -d name=Beta -d slug=beta "$APP/workspaces")" 303
check "alpha is ready (Open lab shown)" "$(browser a "$APP/workspaces/alpha" | grep -o '>Open lab<' | head -1)" ">Open lab<"

lab() { echo "https://$1.actunode.localhost:9443"; }
open_lab() {  # open_lab <cookie jar> <workspace>: the Open lab button; a sleeping lab is woken first (waits for it)
  for _ in $(seq 1 30); do
    result="$(browser "$1" -L -o /dev/null -w '%{http_code} %{url_effective}' --max-redirs 6 "$APP/workspaces/$2/open" || true)"
    [ "$result" = "200 $(lab "$2")/" ] && break; sleep 3
  done; echo "$result"
}
check "alice opens alpha (wake if asleep, SSO round trip)" "$(open_lab a alpha)" "200 $(lab alpha)/"
check "bob opens beta" "$(open_lab b beta)" "200 $(lab beta)/"
check "alpha knows alice" "$(browser a "$(lab alpha)/api/session" | grep -o '"user":"[^"]*","role":"[a-z]*"')" '"user":"dev:alice","role":"operator"'
check "alpha's live feed connects through the edge (browser origin)" "$(browser a --http1.1 -o /dev/null -w '%{http_code}' --max-time 5 -H "Origin: $(lab alpha)" -H 'Connection: Upgrade' -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' "$(lab alpha)/api/ws" || true)" 101
check "a browser POST with the lab's own origin is not treated as cross-site" "$([ "$(post a -H "Origin: $(lab alpha)" "$(lab alpha)/api/validation/reset")" = 403 ] && echo refused || echo accepted)" accepted
check "alpha's robots are online" "$(browser a "$(lab alpha)/api/robots" | grep -o '"connection":"ONLINE"' | wc -l | tr -d ' ')" 3
check "bob cannot open alpha" "$(browser b -L -o /dev/null -w '%{http_code}' --max-redirs 5 "$APP/workspaces/alpha/open")" 404
check "alice's alpha session does not open beta" "$(status a "$(lab beta)/api/robots")" 401
check "a link without the browser's nonce is refused" "$(status c "$(lab alpha)/api/sso?token=x.y")" 401

compose="docker compose -p ws-alpha -f $base/data/workspaces/alpha/compose.yml"
robot_pw="$($compose run --rm mqtt-init add-robot AcmeRobotics amr-7 2>/dev/null | sed -n 's/.*password=\([A-Za-z0-9]*\).*/\1/p')"
$compose kill -s HUP mosquitto >/dev/null 2>&1; sleep 2
backend_pw="$($compose run --rm --entrypoint cat mqtt-init /secrets/backend/password 2>/dev/null)"
mqtt() {  # mqtt <workspace> <user> <password> <topic>
  docker run --rm --network host --add-host "$1.actunode.localhost:127.0.0.1" -v "$CA:/ca.crt:ro" eclipse-mosquitto:2 \
    mosquitto_pub -h "$1.actunode.localhost" -p 18883 --cafile /ca.crt -u "$2" -P "$3" -t "$4" -m '{}' -q 1 \
    >/dev/null 2>&1 && echo accepted || echo refused
}
open_lab a alpha >/dev/null; open_lab b beta >/dev/null  # awake for the next checks (a short idle limit may have stopped them)
check "alpha's robot connects through the edge (TLS, SNI)" "$(mqtt alpha AcmeRobotics.amr-7 "$robot_pw" uagv/v2/AcmeRobotics/amr-7/connection)" accepted
check "alpha's robot login is refused by beta's broker" "$(mqtt beta AcmeRobotics.amr-7 "$robot_pw" uagv/v2/AcmeRobotics/amr-7/connection)" refused
check "alpha's internal backend login is refused from outside" "$(mqtt alpha actunode-backend "$backend_pw" uagv/v2/ActuNode/robot_01/order)" refused
check "alpha's containers cannot reach beta's" "$(docker exec ws-alpha-frontend-1 sh -c 'wget -q -T 3 -O /dev/null http://ws-beta-frontend-1/ >/dev/null 2>&1 && echo reachable || echo unreachable')" unreachable

# The CI token: shown on the workspace page's section, and it logs the CLI runner in through the edge.
check "the workspace page offers the CI token" "$(browser a "$APP/workspaces/alpha" | grep -o 'Show CI token' | head -1)" "Show CI token"
cli="$(dirname "$0")/../../cli/.venv/bin/actunode"
if [ -x "$cli" ]; then
  open_lab a alpha >/dev/null  # a short idle limit may have stopped it
  $compose run --rm --entrypoint cat mqtt-init /secrets/backend/api-token 2>/dev/null > "$work/ci-token"
  code=0; "$cli" test "$(dirname "$0")/../../scenarios/invalid_traffic.yaml" --url "$(lab alpha)" --ca-file "$CA" \
    --token-file "$work/ci-token" >"$work/cli.out" 2>&1 || code=$?
  [ "$code" = 0 ] || sed 's/^/      /' "$work/cli.out"
  check "a scenario runs against alpha from the CLI through the edge" "$code" 0
else
  echo "skip  CLI check: no cli/.venv (python3 -m venv cli/.venv && cli/.venv/bin/pip install ./cli)"
fi

check "alice's account page shows what deletion would do" "$(browser a "$APP/account" | grep -o 'Would be deleted: <code>alpha</code>' | head -1)" "Would be deleted: <code>alpha</code>"
check "a wrong confirmation deletes nothing" "$(post a -d confirm=nope "$APP/account/delete")" 400

# Abuse limits at the edge (phase 2): a flood from one address is slowed, and the app takes small forms only.
flood() {  # 150 requests, 25 at a time: well past the burst of 60
  seq 1 150 | xargs -P 25 -I{} curl -s --cacert "$CA" -o /dev/null -w '%{http_code}\n' "$APP/static/logo.png" | grep -c 429
}
check "a flood from one address is slowed (429s among 150 concurrent requests)" "$([ "$(flood)" -gt 0 ] && echo slowed || echo unslowed)" slowed
sleep 3  # let the limit recover
head -c 100000 /dev/zero | tr '\0' a > "$work/big"
check "a 100 KB form is refused by the edge" "$(post a -H 'Content-Type: application/x-www-form-urlencoded' --data-binary "@$work/big" "$APP/workspaces")" 413

# Idle labs (phase 2): only when the stack was started with a short limit (see local-up.sh), e.g.
# ACTUNODE_IDLE_STOP_S=30 cloud/deploy/local-check.sh
if [ "${ACTUNODE_IDLE_STOP_S:-1800}" -le 120 ]; then
  asleep() { browser "$1" "$APP/workspaces/$2" | grep -o 'Your lab is asleep' | head -1; }
  for _ in $(seq 1 40); do [ "$(asleep a alpha)" = "Your lab is asleep" ] && break; sleep 3; done
  check "alpha falls asleep when nobody uses it" "$(asleep a alpha)" "Your lab is asleep"
  check "a sleeping lab's address leads to the wake page" "$(browser a -o /dev/null -w '%{http_code} %{redirect_url}' "$(lab alpha)/")" "303 $APP/workspaces/alpha/open?edge=1"
  check "a sleeping lab's address is not a way in for strangers" "$(status c "$(lab alpha)/api/robots")" 303
  check "a sleeping lab takes no robot connections" "$(mqtt alpha AcmeRobotics.amr-7 "$robot_pw" uagv/v2/AcmeRobotics/amr-7/connection)" refused
  check "alice wakes alpha" "$(browser a "$APP/workspaces/alpha/open" | grep -o 'Waking up your lab' | head -1)" "Waking up your lab"
  check "alpha is back, with alice signed in" "$(open_lab a alpha)" "200 $(lab alpha)/"
  check "alpha's robot connects again" "$(mqtt alpha AcmeRobotics.amr-7 "$robot_pw" uagv/v2/AcmeRobotics/amr-7/connection)" accepted
  for _ in $(seq 1 40); do [ "$(asleep b beta)" = "Your lab is asleep" ] && break; sleep 3; done
  check "beta sleeps until someone opens it" "$(asleep b beta)" "Your lab is asleep"
fi
exit $fail
