"""Sample of the panel's judge magic-link login (demo_magic_links table +
DemoMagicLoginController + agent:demo-link). Same contract: only a SHA-256 of
the token is kept, links expire, minting revokes older ones, and anything
wrong is a 403. In-memory here because the sample has no database."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


@dataclass
class DemoLink:
    id: int
    email: str
    token_hash: str
    persona: str | None
    expires_at: datetime
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None

    def is_live(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        return self.revoked_at is None and self.expires_at > now


@dataclass
class DemoLinkStore:
    links: dict[int, DemoLink] = field(default_factory=dict)
    _next_id: int = 1

    def mint(self, email: str, persona: str | None = None, days: int = 20,
             now: datetime | None = None) -> tuple[DemoLink, str]:
        now = now or datetime.now(timezone.utc)
        self.revoke(email, now)
        plain = secrets.token_urlsafe(36)
        link = DemoLink(
            id=self._next_id, email=email, token_hash=hashlib.sha256(plain.encode()).hexdigest(),
            persona=persona, expires_at=now + timedelta(days=days),
        )
        self.links[link.id] = link
        self._next_id += 1
        return link, plain

    def revoke(self, email: str, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        n = 0
        for link in self.links.values():
            if link.email == email and link.revoked_at is None:
                link.revoked_at = now
                n += 1
        return n

    def verify(self, token: str, now: datetime | None = None) -> DemoLink | None:
        want = hashlib.sha256(token.encode()).hexdigest()
        for link in self.links.values():
            if link.token_hash == want and link.is_live(now):
                link.last_used_at = now or datetime.now(timezone.utc)
                return link
        return None


store = DemoLinkStore()
