# ActuNode Cloud control plane (D-61)

The service behind **app.actunode.com**: GitHub and Google sign-in, the invite-only beta, workspaces, members and
roles, and the way into each workspace's lab (single sign-on, bound to the browser). Design:
[docs/HOSTED_SERVICE.md](../docs/HOSTED_SERVICE.md). Each workspace's lab is the ordinary ActuNode lab, started by
the provisioner (next).

```bash
cd cloud && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Configuration (environment; secrets are files): `ACTUNODE_CLOUD_DOMAIN`, `ACTUNODE_CLOUD_DB`,
`ACTUNODE_CLOUD_SECRET_FILE`, `ACTUNODE_GITHUB_CLIENT_ID` + `ACTUNODE_GITHUB_CLIENT_SECRET_FILE`,
`ACTUNODE_GOOGLE_CLIENT_ID` + `ACTUNODE_GOOGLE_CLIENT_SECRET_FILE`, `ACTUNODE_CLOUD_ALLOWLIST_FILE` (one
`github:<login>` or email per line), `ACTUNODE_PROVISIONER_URL` + `ACTUNODE_PROVISIONER_TOKEN_FILE`.
