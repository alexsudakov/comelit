from __future__ import annotations

from dataclasses import dataclass
import secrets
import time


SESSION_TTL_SECONDS = 900
MAX_SESSIONS = 256
MAX_MEDIA_GRANTS = 256


class MiniAppSessionError(ValueError):
    """Raised when a Mini App session or action nonce is invalid."""


@dataclass(slots=True)
class MiniAppSession:
    """In-memory authenticated Mini App session."""

    user_id: int
    bot_id: int
    issued_at: int
    expires_at: int
    action_nonce: str


class MiniAppSessionStore:
    """Short-lived in-memory sessions. HA restart intentionally drops them."""

    def __init__(
        self,
        *,
        ttl_seconds: int = SESSION_TTL_SECONDS,
        max_sessions: int = MAX_SESSIONS,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_sessions = max_sessions
        self._sessions: dict[str, MiniAppSession] = {}

    @staticmethod
    def _new_session_token() -> str:
        return secrets.token_urlsafe(32)

    @staticmethod
    def _new_action_nonce() -> str:
        return secrets.token_urlsafe(24)

    def _purge(self, now: int) -> None:
        expired = [
            token
            for token, session in self._sessions.items()
            if session.expires_at <= now
        ]
        for token in expired:
            self._sessions.pop(token, None)

        if len(self._sessions) < self._max_sessions:
            return

        oldest = sorted(
            self._sessions.items(),
            key=lambda item: item[1].issued_at,
        )
        remove_count = len(self._sessions) - self._max_sessions + 1
        for token, _session in oldest[:remove_count]:
            self._sessions.pop(token, None)

    def create(
        self,
        user_id: int,
        bot_id: int,
        *,
        now: int | None = None,
    ) -> tuple[str, MiniAppSession]:
        current = int(time.time()) if now is None else int(now)
        self._purge(current)
        token = self._new_session_token()
        session = MiniAppSession(
            user_id=user_id,
            bot_id=bot_id,
            issued_at=current,
            expires_at=current + self._ttl_seconds,
            action_nonce=self._new_action_nonce(),
        )
        self._sessions[token] = session
        return token, session

    def get(self, token: str, *, now: int | None = None) -> MiniAppSession:
        current = int(time.time()) if now is None else int(now)
        self._purge(current)
        session = self._sessions.get(token)
        if session is None or session.expires_at <= current:
            self._sessions.pop(token, None)
            raise MiniAppSessionError("Mini App session is invalid or expired")
        return session

    def consume_action_nonce(
        self,
        token: str,
        nonce: str,
        *,
        now: int | None = None,
    ) -> MiniAppSession:
        """Atomically consume a nonce before a one-shot Door operation."""
        session = self.get(token, now=now)
        if not nonce or not secrets.compare_digest(session.action_nonce, nonce):
            raise MiniAppSessionError("Mini App action nonce is invalid")
        session.action_nonce = self._new_action_nonce()
        return session

    def delete(self, token: str) -> None:
        self._sessions.pop(token, None)


@dataclass(slots=True)
class MiniAppMediaGrant:
    """Session-bound proxy grant for one HA HLS stream."""

    session_token: str
    upstream_base_path: str
    expires_at: int


class MiniAppMediaGrantStore:
    """Short-lived HLS proxy grants bound to Mini App sessions."""

    def __init__(self, *, max_grants: int = MAX_MEDIA_GRANTS) -> None:
        self._max_grants = max_grants
        self._grants: dict[str, MiniAppMediaGrant] = {}

    def _purge(self, now: int) -> None:
        expired = [
            media_id
            for media_id, grant in self._grants.items()
            if grant.expires_at <= now
        ]
        for media_id in expired:
            self._grants.pop(media_id, None)

        while len(self._grants) >= self._max_grants:
            oldest_media_id = next(iter(self._grants))
            self._grants.pop(oldest_media_id, None)

    def create(
        self,
        session_token: str,
        upstream_base_path: str,
        expires_at: int,
        *,
        now: int | None = None,
    ) -> str:
        current = int(time.time()) if now is None else int(now)
        self._purge(current)
        media_id = secrets.token_urlsafe(24)
        self._grants[media_id] = MiniAppMediaGrant(
            session_token=session_token,
            upstream_base_path=upstream_base_path,
            expires_at=expires_at,
        )
        return media_id

    def get(
        self,
        media_id: str,
        session_token: str,
        *,
        now: int | None = None,
    ) -> MiniAppMediaGrant:
        current = int(time.time()) if now is None else int(now)
        self._purge(current)
        grant = self._grants.get(media_id)
        if (
            grant is None
            or grant.expires_at <= current
            or not secrets.compare_digest(grant.session_token, session_token)
        ):
            raise MiniAppSessionError("Mini App media grant is invalid or expired")
        return grant
