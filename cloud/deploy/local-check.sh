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

check "app answers over HTTPS" "$(status a "$APP/")" 200
check "alice signs in" "$(post a -d login=alice "$APP/dev/login")" 303
check "bob signs in" "$(post b -d login=bob "$APP/dev/login")" 303
check "alice creates workspace alpha" "$(post a --max-time 600 -d name=Alpha -d slug=alpha "$APP/workspaces")" 303
check "bob creates workspace beta" "$(post b --max-time 600 -d name=Beta -d slug=beta "$APP/workspaces")" 303
check "alpha is ready" "$(browser a "$APP/workspaces/alpha" | grep -o 'state: [a-z]*')" "state: ready"

lab() { echo "https://$1.actunode.localhost:9443"; }
check "alice opens alpha (SSO round trip)" "$(browser a -L -o /dev/null -w '%{http_code} %{url_effective}' --max-redirs 5 "$(lab alpha)/api/sso/start")" "200 $(lab alpha)/"
check "alpha knows alice" "$(browser a "$(lab alpha)/api/session" | grep -o '"user":"[^"]*","role":"[a-z]*"')" '"user":"dev:alice","role":"operator"'
check "alpha's robots are online" "$(browser a "$(lab alpha)/api/robots" | grep -o '"connection":"ONLINE"' | wc -l | tr -d ' ')" 3
check "bob cannot open alpha" "$(browser b -L -o /dev/null -w '%{http_code}' --max-redirs 5 "$(lab alpha)/api/sso/start")" 404
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
check "alpha's robot connects through the edge (TLS, SNI)" "$(mqtt alpha AcmeRobotics.amr-7 "$robot_pw" uagv/v2/AcmeRobotics/amr-7/connection)" accepted
check "alpha's robot login is refused by beta's broker" "$(mqtt beta AcmeRobotics.amr-7 "$robot_pw" uagv/v2/AcmeRobotics/amr-7/connection)" refused
check "alpha's internal backend login is refused from outside" "$(mqtt alpha actunode-backend "$backend_pw" uagv/v2/ActuNode/robot_01/order)" refused
check "alpha's containers cannot reach beta's" "$(docker exec ws-alpha-frontend-1 sh -c 'wget -q -T 3 -O /dev/null http://ws-beta-frontend-1/ >/dev/null 2>&1 && echo reachable || echo unreachable')" unreachable
exit $fail
