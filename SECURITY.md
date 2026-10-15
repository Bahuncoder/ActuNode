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
D-18, D-23 to D-26, D-28, D-31, D-32, D-36 and D-41. The latest audit and its fixes: [docs/AUDIT_2026-10-14.md](docs/AUDIT_2026-10-14.md).

Infrastructure measures: broker memory, queue and connection limits; the network listener (8883) has its own
password file without the internal logins; the local CA is name-constrained; containers drop all Linux
capabilities, cannot gain privileges and run with read-only root filesystems; GitHub Actions are pinned to commit
SHAs and kept current by Dependabot.
