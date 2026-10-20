"""The control plane's data (D-61): people, their sign-in identities, workspaces, members, invitations, sessions.

SQLite for the beta (one host); every statement goes through `Store`, so moving to PostgreSQL later touches only
this file. Times are UTC epoch seconds.
"""

import re
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, handle TEXT NOT NULL UNIQUE, email TEXT, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS identities (
  provider TEXT NOT NULL, subject TEXT NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  login TEXT, PRIMARY KEY (provider, subject));
CREATE TABLE IF NOT EXISTS workspaces (
  slug TEXT PRIMARY KEY, name TEXT NOT NULL, sso_key TEXT NOT NULL, created REAL NOT NULL,
  created_by INTEGER NOT NULL REFERENCES users(id), state TEXT NOT NULL DEFAULT 'creating');
CREATE TABLE IF NOT EXISTS members (
  slug TEXT NOT NULL REFERENCES workspaces(slug) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('owner', 'operator', 'viewer')), PRIMARY KEY (slug, user_id));
CREATE TABLE IF NOT EXISTS invitations (
  slug TEXT NOT NULL REFERENCES workspaces(slug) ON DELETE CASCADE, invitee TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('operator', 'viewer')), invited_by INTEGER NOT NULL, created REAL NOT NULL,
  PRIMARY KEY (slug, invitee));
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires REAL NOT NULL);
"""

SLUG = re.compile(r"^[a-z][a-z0-9-]{2,29}[a-z0-9]$")
# Names the service itself uses on actunode.com, or that would confuse people.
RESERVED = {
    "app", "www", "api", "admin", "auth", "login", "mail", "smtp", "status", "docs", "help", "support", "cloud",
    "traefik", "mqtt", "broker", "edge", "dashboard", "billing", "static", "assets", "cdn", "blog", "demo",
}  # fmt: skip
SESSION_S = 7 * 24 * 3600
ROLES = ("owner", "operator", "viewer")


@dataclass(frozen=True)
class User:
    id: int
    handle: str  # what labs and the audit trail show: github:<login> or the Google email
    email: str | None


@dataclass(frozen=True)
class Workspace:
    slug: str
    name: str
    sso_key: str
    state: str
    role: str | None = None  # the asking user's role, where relevant


class Store:
    def __init__(self, path: Path | str):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(SCHEMA)

    def _all(self, sql: str, *args) -> list[tuple]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def _one(self, sql: str, *args) -> tuple | None:
        rows = self._all(sql, *args)
        return rows[0] if rows else None

    def _run(self, *statements: tuple) -> None:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                for sql, *args in statements:
                    self._db.execute(sql, args)
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    # --- people ---------------------------------------------------------------------------------------------

    def user_for_identity(self, provider: str, subject: str, handle: str, email: str | None, login: str) -> User:
        """The user signed in with this identity; created on first sign-in."""
        found = self._one(
            "SELECT u.id, u.handle, u.email FROM identities i JOIN users u ON u.id = i.user_id"
            " WHERE i.provider = ? AND i.subject = ?",
            provider,
            subject,
        )
        if found:
            return self._refresh(User(*found), provider, subject, handle, email, login)
        unique = handle
        while self._one("SELECT 1 FROM users WHERE handle = ?", unique):
            unique = f"{handle[:56]}-{secrets.token_hex(3)}"
        self._run(("INSERT INTO users (handle, email, created) VALUES (?, ?, ?)", unique, email, time.time()))
        user_id = self._one("SELECT id FROM users WHERE handle = ?", unique)[0]
        self._run(("INSERT INTO identities VALUES (?, ?, ?, ?)", provider, subject, user_id, login))
        return User(user_id, unique, email)

    def _refresh(self, user: User, provider: str, subject: str, handle: str, email: str | None, login: str) -> User:
        """Logins and emails change at the provider (a GitHub rename frees the old login for someone else): keep
        what we match invitations against current, at every sign-in, so an invitation to a login reaches whoever
        holds it now.

        The handle does NOT follow: it is the person's identity inside every lab (sessions, revocation, audit
        trail), so it is fixed at the first sign-in. Following a rename would leave lab sessions under the old name
        that a revocation under the new one misses. Someone who later takes the freed login gets a distinct handle
        (a suffix), so two people never share one."""
        self._run(("UPDATE identities SET login = ? WHERE provider = ? AND subject = ?", login, provider, subject),
                  ("UPDATE users SET email = ? WHERE id = ?", email, user.id))  # fmt: skip
        return self.user(user.id)

    def user(self, user_id: int) -> User | None:
        found = self._one("SELECT id, handle, email FROM users WHERE id = ?", user_id)
        return User(*found) if found else None

    def invitees_of(self, user: User) -> set[str]:
        """The names an invitation may use for this person: their GitHub logins and their email."""
        names = {f"github:{login.lower()}" for (login,) in self._all(
            "SELECT login FROM identities WHERE user_id = ? AND provider = 'github'", user.id)}  # fmt: skip
        if user.email:
            names.add(user.email.lower())
        return names

    # --- sessions -------------------------------------------------------------------------------------------

    def new_session(self, user: User) -> str:
        session_id = secrets.token_urlsafe(32)
        self._run(
            ("DELETE FROM sessions WHERE expires < ?", time.time()),
            ("INSERT INTO sessions VALUES (?, ?, ?)", session_id, user.id, time.time() + SESSION_S),
        )
        return session_id

    def session_user(self, session_id: str | None) -> User | None:
        if not session_id:
            return None
        found = self._one("SELECT user_id FROM sessions WHERE id = ? AND expires > ?", session_id, time.time())
        return self.user(found[0]) if found else None

    def end_session(self, session_id: str | None) -> None:
        self._run(("DELETE FROM sessions WHERE id = ?", session_id or ""))

    # --- workspaces -----------------------------------------------------------------------------------------

    def create_workspace(self, slug: str, name: str, owner: User) -> Workspace:
        key = secrets.token_hex(32)
        self._run(
            ("INSERT INTO workspaces (slug, name, sso_key, created, created_by) VALUES (?, ?, ?, ?, ?)",
             slug, name, key, time.time(), owner.id),
            ("INSERT INTO members VALUES (?, ?, 'owner')", slug, owner.id),
        )  # fmt: skip
        return Workspace(slug, name, key, "creating", "owner")

    def slug_taken(self, slug: str) -> bool:
        return self._one("SELECT 1 FROM workspaces WHERE slug = ?", slug) is not None

    def owned_count(self, user: User) -> int:
        return self._one("SELECT COUNT(*) FROM members WHERE user_id = ? AND role = 'owner'", user.id)[0]

    def workspaces_of(self, user: User) -> list[Workspace]:
        rows = self._all(
            "SELECT w.slug, w.name, w.sso_key, w.state, m.role FROM members m JOIN workspaces w ON w.slug = m.slug"
            " WHERE m.user_id = ? ORDER BY w.slug",
            user.id,
        )
        return [Workspace(*row) for row in rows]

    def workspace_for(self, user: User, slug: str) -> Workspace | None:
        row = self._one(
            "SELECT w.slug, w.name, w.sso_key, w.state, m.role FROM members m JOIN workspaces w ON w.slug = m.slug"
            " WHERE m.user_id = ? AND w.slug = ?",
            user.id,
            slug,
        )
        return Workspace(*row) if row else None

    def set_state(self, slug: str, state: str) -> None:
        self._run(("UPDATE workspaces SET state = ? WHERE slug = ?", state, slug))

    def workspaces_in(self, state: str) -> list[Workspace]:
        rows = self._all("SELECT slug, name, sso_key, state FROM workspaces WHERE state = ? ORDER BY slug", state)
        return [Workspace(*row) for row in rows]

    def transition(self, slug: str, from_state: str, to_state: str) -> bool:
        """Move a workspace from one state to another only if it is still in the first: True for the one caller that
        wins (two people waking a lab at the same moment start it once)."""
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                changed = self._db.execute("UPDATE workspaces SET state = ? WHERE slug = ? AND state = ?",
                                           (to_state, slug, from_state)).rowcount  # fmt: skip
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
        return changed == 1

    def delete_workspace(self, slug: str) -> None:
        self._run(("DELETE FROM workspaces WHERE slug = ?", slug))

    # --- members and invitations ----------------------------------------------------------------------------

    def members(self, slug: str) -> list[tuple[User, str]]:
        rows = self._all(
            "SELECT u.id, u.handle, u.email, m.role FROM members m JOIN users u ON u.id = m.user_id"
            " WHERE m.slug = ? ORDER BY m.role, u.handle",
            slug,
        )
        return [(User(*row[:3]), row[3]) for row in rows]

    def invite(self, slug: str, invitee: str, role: str, by: User) -> None:
        self._run(
            ("INSERT OR REPLACE INTO invitations VALUES (?, ?, ?, ?, ?)", slug, invitee, role, by.id, time.time())
        )

    def invitations(self, slug: str) -> list[tuple[str, str]]:
        return self._all("SELECT invitee, role FROM invitations WHERE slug = ? ORDER BY invitee", slug)

    def cancel_invitation(self, slug: str, invitee: str) -> None:
        self._run(("DELETE FROM invitations WHERE slug = ? AND invitee = ?", slug, invitee))

    def has_invitation(self, names: set[str]) -> bool:
        """Before an account exists: is any of these names (github:<login>, email) invited somewhere?"""
        return any(self._one("SELECT 1 FROM invitations WHERE invitee = ?", name) for name in names)

    def is_invited(self, user: User) -> bool:
        names = self.invitees_of(user)
        return any(self._one("SELECT 1 FROM invitations WHERE invitee = ?", name) for name in names)

    def accept_invitations(self, user: User) -> list[str]:
        """Turn this person's open invitations into memberships; the workspaces joined."""
        joined = []
        for name in self.invitees_of(user):
            for slug, role in self._all("SELECT slug, role FROM invitations WHERE invitee = ?", name):
                self._run(
                    ("INSERT OR IGNORE INTO members VALUES (?, ?, ?)", slug, user.id, role),
                    ("DELETE FROM invitations WHERE slug = ? AND invitee = ?", slug, name),
                )
                joined.append(slug)
        return joined

    def set_role(self, slug: str, user_id: int, role: str) -> None:
        self._run(("UPDATE members SET role = ? WHERE slug = ? AND user_id = ?", role, slug, user_id))

    def remove_member(self, slug: str, user_id: int) -> None:
        self._run(("DELETE FROM members WHERE slug = ? AND user_id = ?", slug, user_id))

    def owners(self, slug: str) -> int:
        return self._one("SELECT COUNT(*) FROM members WHERE slug = ? AND role = 'owner'", slug)[0]
