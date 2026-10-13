# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately, not in a public issue. On the GitHub repository open the
**Security** tab and choose **Report a vulnerability** (GitHub private vulnerability reporting).
Include what you found, how to reproduce it, and the affected version or commit.

## Scope

In scope: the backend API, the MQTT broker configuration (accounts, ACLs, listeners), the simulator,
and the web UI (including the nginx proxy in Docker).

Out of scope: vulnerabilities in third-party software themselves (report those upstream), and
deployments that ignore the documented hardening (for example exposing the broker without logins).

## Supported versions

Only the latest `main` and the latest release get fixes.

## Security design

The reasoning behind the security measures is in [docs/DECISIONS.md](docs/DECISIONS.md):
D-18, D-23 to D-26, D-28, D-31, D-32, D-36 and D-41.
