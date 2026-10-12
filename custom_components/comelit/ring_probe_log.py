"""Bounded disclosure of the ring identity probe scalars (owner-authorized).

Diagnostics only.  The native ring probe already prints four markers on the
live native stdout stream::

    V4_RING_PHASE=INITIAL|RETRANSMIT
    V4_RING_PEER_CONNECTION=<4 hex>
    V4_RING_BODY_32_35=<8 hex>|----
    V4_RING_PARSE_STATUS=OK|INSUFFICIENT_LENGTH

Both integration readers classify those keys as ``<redacted>`` and drop them,
so the values reach no read-only surface at all.  This module turns exactly ONE
completed probe batch into exactly ONE bounded log line, without ever returning
a value into a marker collection, tail, summary, failure dump or shadow
snapshot.

Owner-authorized disclosure scope (Python-only, no native change):

    peer_connection : exactly 4 hex digits
    body_32_35      : exactly 8 hex digits

``body_32_35`` stays an OPAQUE call-identity CANDIDATE: its semantics are
unproven and it must never be described as a logical call id.
"""

from __future__ import annotations

import re

RING_PROBE_OWNER_LISTENER = "listener"
RING_PROBE_OWNER_MEDIA = "media"
RING_PROBE_OWNERS = frozenset({RING_PROBE_OWNER_LISTENER, RING_PROBE_OWNER_MEDIA})

RING_PROBE_KEY_PHASE = "V4_RING_PHASE"
RING_PROBE_KEY_PEER_CONNECTION = "V4_RING_PEER_CONNECTION"
RING_PROBE_KEY_BODY_32_35 = "V4_RING_BODY_32_35"
RING_PROBE_KEY_PARSE_STATUS = "V4_RING_PARSE_STATUS"

RING_PROBE_KEYS = frozenset(
    {
        RING_PROBE_KEY_PHASE,
        RING_PROBE_KEY_PEER_CONNECTION,
        RING_PROBE_KEY_BODY_32_35,
        RING_PROBE_KEY_PARSE_STATUS,
    }
)

RING_PROBE_PHASES = frozenset({"INITIAL", "RETRANSMIT"})
RING_PROBE_PARSE_STATUS_OK = "OK"
RING_PROBE_PARSE_STATUS_INSUFFICIENT = "INSUFFICIENT_LENGTH"
RING_PROBE_PARSE_STATUSES = frozenset(
    {RING_PROBE_PARSE_STATUS_OK, RING_PROBE_PARSE_STATUS_INSUFFICIENT}
)
RING_PROBE_BODY_32_35_UNAVAILABLE = "----"

# Bounded value shapes.  These are deliberately NOT merged into the readers'
# global safe-value regexes: widening those would admit a whole new value class
# on EVERY marker key instead of on the two authorized keys.
RING_PROBE_PEER_CONNECTION_RE = re.compile(r"^[0-9a-fA-F]{4}$")
RING_PROBE_BODY_32_35_RE = re.compile(r"^[0-9a-fA-F]{8}$")

RING_PROBE_MISSING_PEER_CONNECTION = "peer_connection"
RING_PROBE_MISSING_BODY_32_35 = "body_32_35"

RING_PROBE_COMPLETE_PREFIX = "Comelit ring identity probe;"
RING_PROBE_INCOMPLETE_PREFIX = "Comelit ring identity probe incomplete;"

RING_PROBE_LOG_PREFIXES = (
    RING_PROBE_COMPLETE_PREFIX,
    RING_PROBE_INCOMPLETE_PREFIX,
)

# body_32_35 is an unverified candidate, never a proven logical call identity.
BODY_32_35_SEMANTICS_PROVEN = False
BODY_32_35_STATUS = "OPAQUE_CALL_ID_CANDIDATE"

# This module is diagnostics only; it never enables a production emit path.
PRODUCTION_EMIT_IMPLEMENTATION = False


class RingProbeDisclosure:
    """Bounded per-owner state machine over the live probe marker stream.

    ``observe`` consumes one native marker key/value pair and returns either a
    single bounded log message or ``None``.  It is total: no input can raise,
    and the only values it can return are the two authorized scalars.
    """

    def __init__(self, owner: str) -> None:
        if owner not in RING_PROBE_OWNERS:
            raise ValueError("ring_probe_owner_invalid")
        self._owner = owner
        self._phase: str | None = None
        self._peer_connection: str | None = None
        self._body_32_35: str | None = None

    @property
    def owner(self) -> str:
        return self._owner

    def reset(self) -> None:
        """Discard the in-flight batch."""
        self._phase = None
        self._peer_connection = None
        self._body_32_35 = None

    def observe(self, key: str, value: str) -> str | None:
        if not isinstance(key, str) or not isinstance(value, str):
            self.reset()
            return None

        if key == RING_PROBE_KEY_PHASE:
            # A new phase always starts a new batch.
            self.reset()
            if value not in RING_PROBE_PHASES:
                return None
            self._phase = value
            return None

        if key == RING_PROBE_KEY_PEER_CONNECTION:
            if self._phase is None:
                return None
            self._peer_connection = (
                value if RING_PROBE_PEER_CONNECTION_RE.fullmatch(value) else None
            )
            return None

        if key == RING_PROBE_KEY_BODY_32_35:
            if self._phase is None:
                return None
            if value == RING_PROBE_BODY_32_35_UNAVAILABLE:
                self._body_32_35 = None
            else:
                self._body_32_35 = (
                    value if RING_PROBE_BODY_32_35_RE.fullmatch(value) else None
                )
            return None

        if key == RING_PROBE_KEY_PARSE_STATUS:
            return self._close_batch(value)

        return None

    def _close_batch(self, parse_status: str) -> str | None:
        phase = self._phase
        peer_connection = self._peer_connection
        body_32_35 = self._body_32_35
        self.reset()

        if phase is None or parse_status not in RING_PROBE_PARSE_STATUSES:
            return None

        if parse_status == RING_PROBE_PARSE_STATUS_OK:
            if peer_connection is None or body_32_35 is None:
                return None
            return (
                f"{RING_PROBE_COMPLETE_PREFIX} owner={self._owner} "
                f"phase={phase} peer_connection={peer_connection} "
                f"body_32_35={body_32_35}"
            )

        missing: list[str] = []
        if peer_connection is None:
            missing.append(RING_PROBE_MISSING_PEER_CONNECTION)
        if body_32_35 is None:
            missing.append(RING_PROBE_MISSING_BODY_32_35)
        if not missing:
            return None
        return (
            f"{RING_PROBE_INCOMPLETE_PREFIX} owner={self._owner} "
            f"phase={phase} missing={','.join(missing)}"
        )
