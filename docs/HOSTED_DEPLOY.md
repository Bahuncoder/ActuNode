# Deploying ActuNode Cloud on actunode.com (D-61)

What the founder does once to put the hosted service ([HOSTED_SERVICE.md](HOSTED_SERVICE.md)) on Hetzner. Accounts,
payments and secrets are yours; everything else is in the repository (`cloud/infra`, `cloud/deploy`). About two
hours the first time, most of it waiting for DNS.

**Before outside users:** phase 2 (monitoring, backups and a restore drill, a security review, terms and privacy) must
be done. Until then, keep the allow list to yourself and people you trust with test data.

## 1. Accounts and tokens

1. **Hetzner Cloud**: create a project (console.hetzner.com) → Security → API tokens → a **Read & Write** token.
   Keep it for step 4.
2. **DNS on Hetzner** (needed for the wildcard certificate): add the zone `actunode.com` in Hetzner's DNS, then at
   the registrar where you bought the domain, set its name servers to the three Hetzner ones shown for the zone.
   Create a **DNS API token** (Hetzner DNS → API tokens). Name-server changes can take a few hours.
3. **GitHub sign-in**: github.com → Settings → Developer settings → OAuth Apps → New OAuth App:
   - Homepage URL: `https://app.actunode.com`
   - Authorization callback URL: `https://app.actunode.com/auth/github/callback`
   Note the Client ID; generate a client secret.
4. **Google sign-in** (optional; GitHub alone works): console.cloud.google.com → APIs & Services → OAuth consent
   screen (External; scopes `openid`, `email`, `profile`) → Credentials → Create OAuth client ID (Web application),
   authorized redirect URI `https://app.actunode.com/auth/google/callback`. Note the Client ID and secret.

## 2. A release with the hosted service

The servers run published images; the hosted service needs a release that includes it (v0.4.0 or later). v0.4.0
(released 24 October 2026) is the first; its images are public on ghcr.io.

## 3. The server (Terraform, no installation needed)

In `cloud/infra/`, create `terraform.tfvars` (ignored by git; it holds your token):

```hcl
hcloud_token   = "<the Hetzner Cloud token>"
ssh_public_key = "ssh-ed25519 AAAA... you@laptop"
admin_cidrs    = ["<your public IP>/32"]   # who may SSH in
location       = "nbg1"                    # or fsn1, hel1
release        = "v0.4.0"
```

Then (Terraform runs in a container):

```bash
cd cloud/infra
docker run --rm -it -v "$PWD":/w -w /w hashicorp/terraform:1.16.6 init
docker run --rm -it -v "$PWD":/w -w /w hashicorp/terraform:1.16.6 apply
```

It creates the server (with Hetzner backups), a 50 GB data volume and the firewall (SSH from your address only;
80, 443 and 8883 open), and prints the DNS records to create.

## 4. DNS records

Create the four records printed by `apply` (A and AAAA for `app.actunode.com` and `*.actunode.com`). Check with
`dig +short app.actunode.com`.

## 5. Secrets and settings on the server

```bash
ssh root@<ipv4>
cd /srv/actunode
openssl rand -hex 32 > secrets/secret
openssl rand -hex 32 > secrets/provisioner-token
printf '%s' '<Hetzner DNS API token>'   > secrets/hetzner-dns-token
printf '%s' '<GitHub client secret>'    > secrets/github-client-secret
printf '%s' '<Google client secret>'    > secrets/google-client-secret   # or leave it out
echo 'github:<your GitHub login>'       > secrets/allowlist            # who may sign in (one per line)
cat >> config.env <<'CFG'
ACME_EMAIL=<your email, for certificate notices>
ACTUNODE_GITHUB_CLIENT_ID=<GitHub client ID>
ACTUNODE_GOOGLE_CLIENT_ID=<Google client ID, or empty>
CFG
```

Optional settings in `config.env`: `ACTUNODE_IDLE_STOP_S` (a lab nobody uses for this many seconds is stopped and
wakes at the next open; default 1800, 0 never) and `ACTUNODE_IDLE_SWEEP_S` (how often the control plane checks;
default 60).

## 6. Start

```bash
/srv/actunode/actunode/cloud/deploy/prod-up.sh
```

The first start requests the wildcard certificate (a minute or two). Then open https://app.actunode.com, sign in with
GitHub, create your workspace, and **Open lab**. Robots connect to `<workspace>.actunode.com:8883` (TLS; the public
certificate, no CA to install).

## 7. Check it like a stranger would

- `curl -sI https://app.actunode.com | grep -i strict-transport` shows HSTS with `includeSubDomains`.
- A second GitHub account not on the allow list sees "invite-only".
- `cloud/deploy/local-check.sh` is the same journey on your computer; run it after every change before deploying.

## Updating

Pull the new release on the server (`git -C /srv/actunode/actunode fetch --tags && git -C /srv/actunode/actunode
checkout vX.Y.Z`), set `ACTUNODE_RELEASE` in `config.env`, run `prod-up.sh`. `prod-up.sh` then upgrades every running
workspace lab, one after the other (each is unavailable for a few seconds); stopped labs upgrade at their next wake.
By hand: `docker compose -f compose.yml -f compose.prod.yml exec -T provisioner /venv/bin/python -m provisioner.app
upgrade`. Right after an upgrade the recreated
edge and control plane are re-attached to every workspace's network by the control plane's first idle sweep, so
labs may answer 502 for up to a minute.

## Backups and restore

`prod-up.sh` installs a systemd timer that runs `cloud/deploy/backup.sh` daily at 03:30 UTC. Each run writes
`/srv/actunode/backups/actunode-<time>.tar.gz` (owner-only) with the control database (SQLite online backup), every
lab's secrets volume (`ws-<slug>_secrets`), the workspace folders with their recordings, and `secrets/` and
`config.env`; the newest 14 are kept (`ACTUNODE_BACKUP_KEEP`). Not included: the Let's Encrypt volume (re-issued) and
images. Run it by hand any time: `sudo /srv/actunode/actunode/cloud/deploy/backup.sh`.

Hetzner's server backups (`backups = true` in Terraform) cover only the server's root disk, not the attached data
volume at `/srv/actunode` and not reliably the Docker volumes. A backup on the same server is not enough: copy the
archives away, encrypted, since they hold sign-on keys, broker passwords, OAuth secrets and customer recordings:

1. On your own computer (not the server): `age-keygen -o actunode-backup.key`. Keep that file safe and off the
   server (a password manager); it is the only way to read the archives. Its public key is the line
   `age1…` the command prints.
2. On the server, put `ACTUNODE_BACKUP_AGE_RECIPIENT=age1…` in `config.env`. From then on each archive is
   `actunode-<time>.tar.gz.age`, encrypted to that key: the server can make backups but cannot read them.
3. Install `rclone`, configure a remote for Hetzner Object Storage or a Storage Box (your account), and put
   `ACTUNODE_BACKUP_REMOTE=<remote>:actunode-backups` in `config.env`; each backup is then copied there (a failed
   copy makes the backup job fail, visible in `systemctl status actunode-backup`). `backup.sh` refuses to copy an
   unencrypted archive off the server (unless the remote is an rclone `crypt` remote and you set
   `ACTUNODE_BACKUP_REMOTE_PLAINTEXT=yes`).

To restore from an encrypted archive, put the key file on the restoring machine and set
`ACTUNODE_BACKUP_AGE_IDENTITY=<path to actunode-backup.key>` for `restore.sh`.

Restore on a new server: Terraform (section 3), put `secrets/` and `config.env` in place (or let the archive supply
them), fetch an archive to the server, then
`ACTUNODE_RESTORE_CONFIRM=yes cloud/deploy/restore.sh <archive>` and `cloud/deploy/prod-up.sh`. `restore.sh` stops the labs
and the control plane, replaces the database, secrets volumes, workspace folders and settings (old folders are kept
as `*.before-restore-<time>`), and starts nothing. Labs start again at their owners' next visit.

`cloud/deploy/restore-drill.sh` proves it on your computer (after `local-up.sh` and `local-check.sh`): it backs up,
destroys the local stack, restores, and checks that the app, the workspace, the lab and a robot's old password work.
Run it after every change to these scripts.

## Monitoring and alerts

`prod-up.sh` installs a systemd timer that runs `cloud/deploy/healthcheck.sh` every 5 minutes. It prints one line per
check (`ok <name>` or `FAIL <name>: <detail>`) and exits 1 on any failure; `--quiet` prints only failures. Checks:

- `app`: `https://app.<domain>/healthz` answers.
- `edge-tls`: the certificate for `app.<domain>` is valid for more than 14 days.
- `control-plane`, `provisioner`: the container is healthy. `edge`: the container is running.
- `disk`: the filesystem holding `/srv/actunode` is below 85 % full (`ACTUNODE_DISK_ALERT_PCT`).
- `backup`: the newest archive in `/srv/actunode/backups` is younger than 36 hours (`ACTUNODE_BACKUP_MAX_AGE_H`).
- `labs`: no running workspace lab has an exited, restarting or unhealthy container (stopped labs are asleep, fine).

Alerts: put `ACTUNODE_ALERT_WEBHOOK=<url>` in `config.env`: a Slack incoming webhook, a Discord webhook or an ntfy
topic URL, your choice. A message (JSON with `text` and `content`; it names the failing checks, never secrets) is
sent when the set of failures changes, including recovery, and once a day while a failure persists. The previous
state is kept in `/srv/actunode/healthcheck.state`. Without a webhook the results only go to the journal
(`journalctl -u actunode-healthcheck`). Run it by hand any time: `sudo /srv/actunode/actunode/cloud/deploy/healthcheck.sh`.

A check on the server cannot tell you the server is down. Also set up an outside uptime monitor (UptimeRobot or
similar, free tier) on `https://app.<domain>/healthz`; that is your account to create. The labs' own metrics
(`/api/metrics`, D-57) are available for a Prometheus later.
