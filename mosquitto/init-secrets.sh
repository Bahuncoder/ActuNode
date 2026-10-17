#!/bin/sh
# Credentials for ActuNode: MQTT logins (D-23) and the web login token (D-25). Runs as root in the eclipse-mosquitto image, writing into the
# mqtt-secrets volume mounted at /secrets. Each consumer gets its own folder, readable only by it:
#
#   /secrets/broker/     passwd, passwd.net (hashed), acl, healthcheck.password -> owned by mosquitto (1883)
#   /secrets/backend/    password, api-token                     -> owned by BACKEND_UID
#   /secrets/simulator/  password (shared by robot_01..robot_NN) -> owned by SIMULATOR_UID
#   /secrets/people/     tools.password                          -> root only; shown with `show tools`
#   /secrets/robots/     <manufacturer>.<serial>.password        -> root only; shown when added
#   /secrets/masters/    <name>.password, <name>.manufacturers   -> root only; shown when added
#   /secrets/ros2/       password (the ROS 2 robot, ROS2.nav2_01) -> owned by ROS2_UID (D-51)
#   /secrets/users/      <name>.role, <name>.sha256 (web logins, D-56) -> root only; the token is shown once, never kept
#   /secrets/backend/users   name:role:sha256 per web login, rebuilt on every run -> owned by BACKEND_UID
#
# Passwords are created once and kept; the hashed password file and the ACL are rebuilt on every start.
# A robot logs in as <manufacturer>.<serial> (D-28): VDA 5050 serial numbers are unique per manufacturer
# only, so the login names both, and its ACL block pins both topic levels (VDA major versions v2 and v3).
#
#   (no argument)        create missing passwords, rebuild the password files and ACL
#   show tools           print the read-only tools password
#   show api-token       print the token for the web login (needed when ACTUNODE_REQUIRE_LOGIN=1)
#   add-robot <manufacturer> <serial>   create a login for a real robot and print its password
#   add-master <name> [<manufacturer> ...]   create a login for an outside master control (fleet manager) that
#                        commands the robots of these manufacturers (default ActuNode: the simulated ones), D-47
#   remove-robot <manufacturer> <serial> | remove-master <name>   delete a login
#   add-user <name> operator|viewer   a web login for one person (D-56); prints its token once. Viewers can look,
#                        not change anything. Takes effect at once (the backend re-reads the users file)
#   remove-user <name> | list-users   delete a web login (its open sessions end within seconds) | list them
#   rotate tools | api-token | robot <manufacturer> <serial> | master <name> | user <name>   new password or
#                        token, printed (old one stops working)
#   backup               write a tar of all credentials and certificates to stdout (keep it secret)
#   restore              read such a tar from stdin, check its layout, replace the credentials
#
# Apply a change without disconnecting anybody: `docker compose kill -s HUP mosquitto` (the broker reloads its
# password files and ACL). Rotating the api-token also needs `docker compose restart backend`.
#
# A master control logs in as master@<name>: robot logins never contain @, so the two cannot collide.
# Two password files are built: broker/passwd (all logins; ports 1883 and 9001, inside Docker and on this computer)
# and broker/passwd.net (tools, real robots, master controls; the TLS port 8883): the backend, the health check and
# the simulated robots cannot log in from the network. Topics carry explicit VDA major versions (v2, v3): a login can
# only create retained topics under those.
set -eu
umask 077
S=/secrets
BACKEND_UID="${BACKEND_UID:-1000}"
SIMULATOR_UID="${SIMULATOR_UID:-1000}"
SIM_MAX_ROBOTS="${SIM_MAX_ROBOTS:-50}"
ROS2_UID="${ROS2_UID:-1000}"
ROS2_LOGIN="ROS2.nav2_01"  # the optional ROS 2 robot (profile ros2, D-51): a robot login like a real robot's
VERSIONS="v2 v3"  # VDA 5050 major versions the backend and simulator speak (SUPPORTED_MAJOR_VERSIONS)
HUP="docker compose kill -s HUP mosquitto"

new_password() { head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32; }

ensure() {  # ensure <file>: create a password file once
  [ -s "$1" ] || new_password > "$1"
}

valid_name() {  # manufacturer and serial become a username and ACL topic levels: no . / + # or spaces
  printf '%s' "$1" | grep -Eq '^[A-Za-z0-9_-]{1,64}$'
}

is_sim_robot() {  # is_sim_robot <manufacturer> <serial>: one of the simulated robots (their login is shared)
  [ "$1" = ActuNode ] || return 1
  n=1
  while [ "$n" -le "$SIM_MAX_ROBOTS" ]; do
    [ "$2" = "$(printf 'robot_%02d' "$n")" ] && return 0
    n=$((n + 1))
  done
  return 1
}

robot_acl() {  # robot_acl <manufacturer> <serial> [sim]: own robot-to-master topics write, own commands read
  echo
  echo "user $1.$2"
  for v in $VERSIONS; do
    for t in state connection visualization factsheet; do echo "topic write uagv/$v/$1/$2/$t"; done
    for t in order instantActions zoneSet responses; do echo "topic read uagv/$v/$1/$2/$t"; done
  done
  [ "${3:-}" = sim ] && echo "topic read actunode/v1/sim/$2/inject"
  return 0
}

master_acl() {  # master_acl <name> <manufacturer>...: commands to those robots write, their traffic read
  name="$1"; shift
  echo
  echo "user master@$name"
  for m in "$@"; do
    for v in $VERSIONS; do
      for t in order instantActions zoneSet responses; do echo "topic write uagv/$v/$m/+/$t"; done
      echo "topic read uagv/$v/$m/#"
    done
  done
  return 0
}

usage_exit() { echo "usage: $1" >&2; exit 2; }
check_user() {  # web login names: lower case, as the backend expects (auth.USER_LINE); admin and local are taken
  printf '%s' "$1" | grep -Eq '^[a-z0-9][a-z0-9_.-]{0,31}$' ||
    { echo "invalid user name: '$1' (lower-case letters, digits, . _ -; up to 32)" >&2; exit 2; }
  case "$1" in admin|local) echo "refused: '$1' is reserved (admin is the shared api-token, local is login off)" >&2; exit 2 ;; esac
}
new_user_token() {  # new_user_token <name>: a fresh token; only its hash is kept
  mkdir -p "$S/users"
  token="$(new_password)"
  printf '%s' "$token" | sha256sum | cut -d' ' -f1 > "$S/users/$1.sha256"
  web_note="web login: user=$1 role=$(cat "$S/users/$1.role") token=$token
shown once (the lab keeps only its hash); it works at once, no restart"
}
check_name() {  # check_name <what> <value>
  valid_name "$2" || { echo "invalid $1: '$2' (letters, digits, _ and - only)" >&2; exit 2; }
}

# One run at a time (two at once could install a password file that misses logins, I12).
mkdir -p "$S"
exec 9> "$S/.lock"
flock 9

new_robot="" new_master="" note="" web_note=""
case "${1:-}" in
  show)
    case "${2:-}" in
      tools) cat "$S/people/tools.password" ;;
      api-token) cat "$S/backend/api-token" ;;
      *) usage_exit "show tools | show api-token" ;;
    esac
    echo
    exit 0 ;;
  backup)
    [ $# -eq 1 ] || usage_exit "backup > file.tar"
    [ -t 1 ] && { echo "backup writes a tar to stdout: redirect it to a file" >&2; exit 2; }
    tar -C "$S" --exclude ./.lock --exclude './.restore.*' -cf - .
    exit 0 ;;
  restore)
    [ $# -eq 1 ] || usage_exit "restore < file.tar"
    work="$(mktemp -d "$S/.restore.XXXXXX")"
    trap 'rm -rf "$work"' EXIT
    cat > "$work/in.tar"
    tar -tvf "$work/in.tar" | awk '
      { t = substr($1, 1, 1); n = $NF }
      (t != "-" && t != "d") || n ~ /^\// || n ~ /(^|\/)\.\.(\/|$)/ ||
        (n !~ /^(\.\/)?(backend|simulator|people|robots|masters|users|ros2|public|ca|web|broker)(\/|$)/ && n !~ /^\.\/?$/) { bad = 1 }
      END { exit bad }' || { echo "restore: not a backup made by 'backup' (unexpected entry); nothing changed" >&2; exit 1; }
    mkdir "$work/x"
    tar -xf "$work/in.tar" -C "$work/x"
    for f in backend/password backend/api-token simulator/password people/tools.password; do
      [ -s "$work/x/$f" ] || { echo "restore: backup lacks $f; nothing changed" >&2; exit 1; }
    done
    for d in backend simulator people robots masters users ros2 public ca web broker; do
      [ -d "$work/x/$d" ] || continue
      rm -rf "${S:?}/$d"
      mv "$work/x/$d" "$S/$d"
    done
    rm -rf "$work"
    echo "restore: credentials restored; run: docker compose up -d --force-recreate mqtt-init cert-init mosquitto backend simulator frontend" ;;
  add-robot)
    [ $# -eq 3 ] || usage_exit "add-robot <manufacturer> <serial>"
    check_name manufacturer "$2"; check_name "serial number" "$3"
    if is_sim_robot "$2" "$3"; then
      echo "refused: ActuNode.$3 is a simulated robot (ACTUNODE_SIM_ROBOTS, up to $SIM_MAX_ROBOTS); use another manufacturer or serial" >&2
      exit 2
    fi
    if [ "$2.$3" = "$ROS2_LOGIN" ]; then
      echo "refused: $ROS2_LOGIN is the ROS 2 robot's login (profile ros2); use another manufacturer or serial" >&2
      exit 2
    fi
    new_robot="$2.$3"
    mkdir -p "$S/robots"
    ensure "$S/robots/$new_robot.password" ;;
  add-master)
    [ $# -ge 2 ] || usage_exit "add-master <name> [<manufacturer> ...]"
    check_name name "$2"
    new_master="$2"
    shift 2
    [ $# -gt 0 ] || set -- ActuNode
    for m in "$@"; do check_name manufacturer "$m"; done
    mkdir -p "$S/masters"
    ensure "$S/masters/$new_master.password"
    printf '%s\n' "$@" > "$S/masters/$new_master.manufacturers" ;;
  remove-robot)
    [ $# -eq 3 ] || usage_exit "remove-robot <manufacturer> <serial>"
    check_name manufacturer "$2"; check_name "serial number" "$3"
    [ -e "$S/robots/$2.$3.password" ] || { echo "no robot login $2.$3" >&2; exit 1; }
    rm -f "$S/robots/$2.$3.password"
    note="removed robot login $2.$3" ;;
  remove-master)
    [ $# -eq 2 ] || usage_exit "remove-master <name>"
    check_name name "$2"
    [ -e "$S/masters/$2.password" ] || { echo "no master control login $2" >&2; exit 1; }
    rm -f "$S/masters/$2.password" "$S/masters/$2.manufacturers"
    note="removed master control login master@$2" ;;
  add-user)
    [ $# -eq 3 ] || usage_exit "add-user <name> operator|viewer"
    check_user "$2"
    case "$3" in operator|viewer) ;; *) usage_exit "add-user <name> operator|viewer" ;; esac
    [ -e "$S/users/$2.sha256" ] && { echo "user $2 exists; new token: rotate user $2" >&2; exit 1; }
    mkdir -p "$S/users"
    printf '%s\n' "$3" > "$S/users/$2.role"
    new_user_token "$2" ;;
  remove-user)
    [ $# -eq 2 ] || usage_exit "remove-user <name>"
    check_user "$2"
    [ -e "$S/users/$2.sha256" ] || { echo "no user $2" >&2; exit 1; }
    rm -f "$S/users/$2.sha256" "$S/users/$2.role"
    web_note="removed user $2 (their open sessions end within seconds)" ;;
  list-users)
    [ $# -eq 1 ] || usage_exit "list-users"
    echo "admin operator (the shared api-token)"
    for f in "$S"/users/*.sha256; do
      [ -e "$f" ] || continue
      name="$(basename "$f" .sha256)"
      echo "$name $(cat "$S/users/$name.role" 2>/dev/null || echo '?')"
    done
    exit 0 ;;
  rotate)
    case "${2:-}" in
      tools)
        [ $# -eq 2 ] || usage_exit "rotate tools"
        rm -f "$S/people/tools.password"; mkdir -p "$S/people"; ensure "$S/people/tools.password"
        note="new tools password: $(cat "$S/people/tools.password")" ;;
      api-token)
        [ $# -eq 2 ] || usage_exit "rotate api-token"
        rm -f "$S/backend/api-token"; mkdir -p "$S/backend"; ensure "$S/backend/api-token"
        note="new api token: $(cat "$S/backend/api-token")
the backend reads it at start: docker compose restart backend (everybody logged in to the web UI must log in again)" ;;
      robot)
        [ $# -eq 4 ] || usage_exit "rotate robot <manufacturer> <serial>"
        check_name manufacturer "$3"; check_name "serial number" "$4"
        [ -e "$S/robots/$3.$4.password" ] || { echo "no robot login $3.$4" >&2; exit 1; }
        rm -f "$S/robots/$3.$4.password"; ensure "$S/robots/$3.$4.password"
        note="robot login: username=$3.$4 password=$(cat "$S/robots/$3.$4.password")" ;;
      master)
        [ $# -eq 3 ] || usage_exit "rotate master <name>"
        check_name name "$3"
        [ -e "$S/masters/$3.password" ] || { echo "no master control login $3" >&2; exit 1; }
        rm -f "$S/masters/$3.password"; ensure "$S/masters/$3.password"
        note="master control login: username=master@$3 password=$(cat "$S/masters/$3.password")" ;;
      user)
        [ $# -eq 3 ] || usage_exit "rotate user <name>"
        check_user "$3"
        [ -e "$S/users/$3.sha256" ] || { echo "no user $3" >&2; exit 1; }
        new_user_token "$3" ;;
      *) usage_exit "rotate tools | api-token | robot <manufacturer> <serial> | master <name> | user <name>" ;;
    esac ;;
  "") ;;
  *) echo "unknown command: $1" >&2; exit 2 ;;
esac

mkdir -p "$S/broker" "$S/backend" "$S/simulator" "$S/people" "$S/robots" "$S/masters" "$S/users" "$S/ros2"
ensure "$S/backend/password"
ensure "$S/backend/api-token"
ensure "$S/simulator/password"
ensure "$S/ros2/password"
ensure "$S/people/tools.password"
ensure "$S/broker/healthcheck.password"

tmp="$(mktemp "$S/broker/passwd.XXXXXX")"
tmpnet="$(mktemp "$S/broker/passwd.net.XXXXXX")"
acl="$(mktemp "$S/broker/acl.XXXXXX")"
users="$(mktemp "$S/backend/users.XXXXXX")"
trap 'rm -f "$tmp" "$tmpnet" "$acl" "$users"' EXIT
: > "$tmp"; : > "$tmpnet"
cat /acl.base > "$acl"
add() {  # add <login> <password file> [net]: net logins also go in the network listener's file
  mosquitto_passwd -b "$tmp" "$1" "$(cat "$2")" > /dev/null
  [ "${3:-}" = net ] && mosquitto_passwd -b "$tmpnet" "$1" "$(cat "$2")" > /dev/null
  return 0
}
add actunode-backend "$S/backend/password"
add tools "$S/people/tools.password" net
add healthcheck "$S/broker/healthcheck.password"
echo >> "$acl"; echo "# --- generated by mqtt-init: one block per robot login ---" >> "$acl"
i=1
while [ "$i" -le "$SIM_MAX_ROBOTS" ]; do
  serial="$(printf 'robot_%02d' "$i")"
  add "ActuNode.$serial" "$S/simulator/password"
  robot_acl ActuNode "$serial" sim >> "$acl"
  i=$((i + 1))
done
# The ROS 2 robot connects like a real robot: over TLS (8883), with its own robot ACL block.
add "$ROS2_LOGIN" "$S/ros2/password" net
robot_acl "${ROS2_LOGIN%%.*}" "${ROS2_LOGIN#*.}" >> "$acl"
for f in "$S"/robots/*.password; do
  [ -e "$f" ] || continue
  login="$(basename "$f" .password)"
  manufacturer="${login%%.*}" serial="${login#*.}"
  if [ "$manufacturer" = "$login" ] || ! valid_name "$manufacturer" || ! valid_name "$serial"; then
    echo "mqtt-init: WARNING: ignoring robot login '$login' (logins are now <manufacturer>.<serial>, D-28);" \
      "re-create it with: add-robot <manufacturer> $login" >&2
    continue
  fi
  if [ "$login" = "$ROS2_LOGIN" ]; then
    echo "mqtt-init: WARNING: ignoring robot login '$login' (the ROS 2 robot's name; remove it: remove-robot ${login%%.*} ${login#*.})" >&2
    continue
  fi
  if is_sim_robot "$manufacturer" "$serial"; then
    echo "mqtt-init: WARNING: ignoring robot login '$login' (a simulated robot's name; remove it: remove-robot $manufacturer $serial)" >&2
    continue
  fi
  add "$login" "$f" net
  robot_acl "$manufacturer" "$serial" >> "$acl"
done
echo >> "$acl"; echo "# --- generated by mqtt-init: one block per master control login (D-47) ---" >> "$acl"
for f in "$S"/masters/*.password; do
  [ -e "$f" ] || continue
  name="$(basename "$f" .password)"
  manufacturers="$(cat "$S/masters/$name.manufacturers" 2>/dev/null || echo ActuNode)"
  ok=1
  valid_name "$name" || ok=0
  for m in $manufacturers; do valid_name "$m" || ok=0; done
  if [ "$ok" -ne 1 ] || [ -z "$manufacturers" ]; then
    echo "mqtt-init: WARNING: ignoring master control login '$name' (invalid name or manufacturers)" >&2
    continue
  fi
  add "master@$name" "$f" net
  # shellcheck disable=SC2086 # one manufacturer per word, each checked by valid_name above
  master_acl "$name" $manufacturers >> "$acl"
done
# Web logins for the backend (D-56): name:role:sha256, only well-formed entries.
for f in "$S"/users/*.sha256; do
  [ -e "$f" ] || continue
  name="$(basename "$f" .sha256)" role="$(cat "$S/users/$(basename "$f" .sha256).role" 2>/dev/null || true)" hash="$(cat "$f")"
  if ! printf '%s' "$name" | grep -Eq '^[a-z0-9][a-z0-9_.-]{0,31}$' || [ "$name" = admin ] || [ "$name" = local ] ||
    { [ "$role" != operator ] && [ "$role" != viewer ]; } || ! printf '%s' "$hash" | grep -Eq '^[0-9a-f]{64}$'; then
    echo "mqtt-init: WARNING: ignoring web login '$name' (invalid name, role or hash)" >&2
    continue
  fi
  echo "$name:$role:$hash" >> "$users"
done
mv "$users" "$S/backend/users"
mv "$tmp" "$S/broker/passwd"
mv "$tmpnet" "$S/broker/passwd.net"
mv "$acl" "$S/broker/acl"

chown -R 1883:1883 "$S/broker"
chown -R "$BACKEND_UID" "$S/backend"
chown -R "$SIMULATOR_UID" "$S/simulator"
chown -R "$ROS2_UID" "$S/ros2"
chmod 500 "$S/broker" "$S/backend" "$S/simulator" "$S/ros2"
chmod 400 "$S/broker/passwd" "$S/broker/passwd.net" "$S/broker/acl" "$S/broker/healthcheck.password" \
  "$S/backend/password" "$S/backend/api-token" "$S/backend/users" "$S/simulator/password" "$S/ros2/password"
chmod -R go-rwx "$S/people" "$S/robots" "$S/masters" "$S/users"
echo "mqtt-init: credentials ready ($SIM_MAX_ROBOTS simulated robots)"
if [ -n "$new_robot" ]; then
  echo "robot login: username=$new_robot password=$(cat "$S/robots/$new_robot.password")"
fi
if [ -n "$new_master" ]; then
  echo "master control login: username=master@$new_master password=$(cat "$S/masters/$new_master.password")"
  echo "it commands: $(tr '\n' ' ' < "$S/masters/$new_master.manufacturers")"
fi
[ -n "$note" ] && echo "$note"
[ -n "$web_note" ] && echo "$web_note"
if [ -n "$new_robot$new_master$note" ]; then
  echo "apply it without disconnecting anybody: $HUP"
fi
exit 0
