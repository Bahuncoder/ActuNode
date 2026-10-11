#!/bin/sh
# Credentials for ActuNode: MQTT logins (D-23) and the web login token (D-25). Runs as root in the eclipse-mosquitto image, writing into the
# mqtt-secrets volume mounted at /secrets. Each consumer gets its own folder, readable only by it:
#
#   /secrets/broker/     passwd (hashed), healthcheck.password   -> owned by mosquitto (1883)
#   /secrets/backend/    password, api-token                     -> owned by BACKEND_UID
#   /secrets/simulator/  password (shared by robot_01..robot_NN) -> owned by SIMULATOR_UID
#   /secrets/people/     tools.password                          -> root only; shown with `show tools`
#   /secrets/robots/     <serial>.password for real robots       -> root only; shown when added
#
# Passwords are created once and kept; the hashed password file is rebuilt on every start.
#
#   (no argument)        create missing passwords, rebuild the password file
#   show tools           print the read-only tools password
#   show api-token       print the token for the web login (needed when ACTUNODE_REQUIRE_LOGIN=1)
#   add-robot <serial>   create a login for a real robot and print its password
set -eu
umask 077
S=/secrets
BACKEND_UID="${BACKEND_UID:-1000}"
SIMULATOR_UID="${SIMULATOR_UID:-1000}"
SIM_MAX_ROBOTS="${SIM_MAX_ROBOTS:-50}"

new_password() { head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32; }

ensure() {  # ensure <file>: create a password file once
  [ -s "$1" ] || new_password > "$1"
}

valid_serial() {  # serial numbers become usernames and ACL topic levels: no / + # or spaces
  printf '%s' "$1" | grep -Eq '^[A-Za-z0-9_-]{1,64}$'
}

new_robot=""
case "${1:-}" in
  show)
    case "${2:-}" in
      tools) cat "$S/people/tools.password" ;;
      api-token) cat "$S/backend/api-token" ;;
      *) echo "usage: show tools | show api-token" >&2; exit 2 ;;
    esac
    echo
    exit 0 ;;
  add-robot)
    new_robot="${2:-}"
    valid_serial "$new_robot" || { echo "invalid serial number: '$new_robot' (letters, digits, _ and - only)" >&2; exit 2; }
    mkdir -p "$S/robots"
    ensure "$S/robots/$new_robot.password" ;;
  "") ;;
  *) echo "unknown command: $1" >&2; exit 2 ;;
esac

mkdir -p "$S/broker" "$S/backend" "$S/simulator" "$S/people" "$S/robots"
ensure "$S/backend/password"
ensure "$S/backend/api-token"
ensure "$S/simulator/password"
ensure "$S/people/tools.password"
ensure "$S/broker/healthcheck.password"

tmp="$S/broker/passwd.new"
rm -f "$tmp"; : > "$tmp"
add() { mosquitto_passwd -b "$tmp" "$1" "$(cat "$2")" > /dev/null; }
add actunode-backend "$S/backend/password"
add tools "$S/people/tools.password"
add healthcheck "$S/broker/healthcheck.password"
i=1
while [ "$i" -le "$SIM_MAX_ROBOTS" ]; do
  add "$(printf 'robot_%02d' "$i")" "$S/simulator/password"
  i=$((i + 1))
done
for f in "$S"/robots/*.password; do
  [ -e "$f" ] || continue
  serial="$(basename "$f" .password)"
  valid_serial "$serial" && add "$serial" "$f"
done
mv "$tmp" "$S/broker/passwd"

chown -R 1883:1883 "$S/broker"
chown -R "$BACKEND_UID" "$S/backend"
chown -R "$SIMULATOR_UID" "$S/simulator"
chmod 500 "$S/broker" "$S/backend" "$S/simulator"
chmod 400 "$S/broker/passwd" "$S/broker/healthcheck.password" "$S/backend/password" "$S/backend/api-token" \
  "$S/simulator/password"
chmod -R go-rwx "$S/people" "$S/robots"
echo "mqtt-init: credentials ready ($SIM_MAX_ROBOTS simulated robots)"
if [ -n "$new_robot" ]; then
  echo "robot login: username=$new_robot password=$(cat "$S/robots/$new_robot.password")"
  echo "apply it: docker compose up -d --force-recreate mqtt-init mosquitto"
fi
