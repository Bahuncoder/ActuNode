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

The servers run published images; the hosted service needs a release that includes it (v0.4.0 or later). When the
v0.4.0 release is tagged (as before: tag, push, `gh release create`, packages public), its images are on ghcr.io.

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
checkout vX.Y.Z`), set `ACTUNODE_RELEASE` in `config.env`, run `prod-up.sh`. Existing workspace labs keep their
version until restarted by the provisioner (phase 2 adds rolling upgrades). Right after an upgrade the recreated
edge and control plane are re-attached to every workspace's network by the control plane's first idle sweep, so
labs may answer 502 for up to a minute.
