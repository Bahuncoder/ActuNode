#!/bin/sh
# TLS certificates for sharing the lab (issue 12 part C2, D-26). Runs as root in python:3.12-slim
# (which has openssl), writing into the secrets volume mounted at /secrets:
#
#   /secrets/ca/            ca.key, ca.crt     local certificate authority (key never leaves here)
#   /secrets/broker/tls/    server.crt/.key    mosquitto, port 8883      -> owned by mosquitto (1883)
#   /secrets/web/           server.crt/.key    nginx, port 443 (8443)    -> owned by nginx (101, non-root)
#   /secrets/people/ca.crt                     what browsers and robots trust: `show ca`
#
# The CA is made once (10 years). The server certificate covers localhost, 127.0.0.1, ::1, mosquitto
# and every name in ACTUNODE_ALLOWED_HOSTS; it is renewed when that list changes or within 30 days of
# expiry.
#
# The CA is limited (I3): pathlen:0 (it signs only server certificates) and critical name constraints, so even if
# its key is stolen the CA cannot vouch for other sites: only the names above, loopback and private address ranges.
# A name added to ACTUNODE_ALLOWED_HOSTS later that the CA does not permit needs `recreate-ca`.
#
#   (no argument)   create or renew
#   show ca         print the CA certificate (import it in browsers / give it to robots)
#   recreate-ca     delete the CA and issue new certificates (everybody must import the new CA again)
set -eu
umask 077
S=/secrets

if [ "${1:-}" = show ]; then
  [ "${2:-}" = ca ] || { echo "usage: show ca" >&2; exit 2; }
  cat "$S/people/ca.crt"
  exit 0
fi
if [ "${1:-}" = recreate-ca ]; then
  rm -rf "${S:?}/ca" "$S/people/ca.crt"
elif [ -n "${1:-}" ]; then
  echo "unknown command: $1" >&2; exit 2
fi

mkdir -p "$S/ca" "$S/broker/tls" "$S/web" "$S/people"

# Subject alternative names: fixed local names plus ACTUNODE_ALLOWED_HOSTS (IPs as IP:, names as DNS:).
sans="DNS:localhost,IP:127.0.0.1,IP:0:0:0:0:0:0:0:1,DNS:mosquitto"
# Name constraints for the CA: the same names, loopback, and private ranges (IPs need their netmask in address form).
v6full=ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff
ncons="permitted;DNS:localhost,permitted;DNS:mosquitto,permitted;IP:127.0.0.0/255.0.0.0,permitted;IP:::1/$v6full"
ncons="$ncons,permitted;IP:10.0.0.0/255.0.0.0,permitted;IP:172.16.0.0/255.240.0.0,permitted;IP:192.168.0.0/255.255.0.0"
ncons="$ncons,permitted;IP:fc00::/fe00::,permitted;IP:fe80::/ffc0::"
for host in $(echo "${ACTUNODE_ALLOWED_HOSTS:-}" | tr ',' ' '); do
  case "$host" in
    localhost|127.0.0.1|::1) ;;
    *[!0-9.]*) case "$host" in
        *:*) sans="$sans,IP:$host"; ncons="$ncons,permitted;IP:$host/$v6full" ;;
        *) sans="$sans,DNS:$host"; ncons="$ncons,permitted;DNS:$host" ;;
      esac ;;
    *) sans="$sans,IP:$host"; ncons="$ncons,permitted;IP:$host/255.255.255.255" ;;
  esac
done

if [ ! -s "$S/ca/ca.crt" ]; then
  openssl req -x509 -new -nodes -newkey ec -pkeyopt ec_paramgen_curve:P-256 -sha256 -days 3650 \
    -keyout "$S/ca/ca.key" -out "$S/ca/ca.crt" -subj "/CN=ActuNode local CA" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -addext "nameConstraints=critical,$ncons" 2>/dev/null
  echo "cert-init: created a local certificate authority"
fi
openssl x509 -in "$S/ca/ca.crt" -noout -text | grep -q "Name Constraints" ||
  echo "cert-init: NOTE: this CA predates name constraints (I3); to replace it: docker compose run --rm cert-init recreate-ca"

renew=no
[ -s "$S/web/server.crt" ] || renew=yes
[ "$(cat "$S/ca/sans" 2>/dev/null || true)" = "$sans" ] || renew=yes
[ "$renew" = no ] && ! openssl x509 -checkend 2592000 -noout -in "$S/web/server.crt" >/dev/null && renew=yes

if [ "$renew" = yes ]; then
  work=$(mktemp -d)
  openssl req -new -nodes -newkey ec -pkeyopt ec_paramgen_curve:P-256 -sha256 \
    -keyout "$work/server.key" -out "$work/server.csr" -subj "/CN=ActuNode" 2>/dev/null
  printf 'subjectAltName=%s\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\n' \
    "$sans" > "$work/ext"
  openssl x509 -req -sha256 -days 825 -in "$work/server.csr" -CA "$S/ca/ca.crt" -CAkey "$S/ca/ca.key" \
    -CAcreateserial -CAserial "$S/ca/ca.srl" -extfile "$work/ext" -out "$work/server.crt" 2>/dev/null
  if ! openssl verify -CAfile "$S/ca/ca.crt" "$work/server.crt" >/dev/null 2>&1; then
    rm -rf "$work"
    echo "cert-init: ERROR: the CA does not permit these names ($sans); run: docker compose run --rm cert-init recreate-ca" >&2
    exit 1
  fi
  for dir in "$S/broker/tls" "$S/web"; do
    cp "$work/server.crt" "$work/server.key" "$dir/"
  done
  rm -rf "$work"
  echo "$sans" > "$S/ca/sans"
  echo "cert-init: server certificate for $sans"
fi

cp "$S/ca/ca.crt" "$S/people/ca.crt"
cp "$S/ca/ca.crt" "$S/broker/tls/ca.crt"
chown -R 1883:1883 "$S/broker/tls"
chown -R 101:101 "$S/web"
chmod 500 "$S/broker/tls" "$S/web"
chmod 400 "$S/broker/tls/server.key" "$S/web/server.key"
chmod 444 "$S/broker/tls/server.crt" "$S/broker/tls/ca.crt" "$S/web/server.crt" "$S/people/ca.crt"
chmod -R go-rwx "$S/ca"
echo "cert-init: certificates ready"
