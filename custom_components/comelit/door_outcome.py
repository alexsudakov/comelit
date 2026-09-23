from __future__ import annotations

DOOR_ONE_SHOT_WRITE_COUNT = 5
_DOOR_SEQUENCE_SENT_STATES = frozenset({"ACKED", "UNKNOWN_OUTCOME"})


def door_one_shot_sequence_sent(
    *,
    state: object,
    write_count: object,
    existing_ctpp_reused: object,
) -> bool:
    """Return whether the complete validated Door TX sequence left HA locally.

    This is deliberately weaker than protocol acknowledgement and must never be
    used to assert a physical door effect.  It only means that all five
    persistent-CTPP Door writes crossed the native PseudoTCP TX-completion
    boundary on the already-registered CTPP channel.
    """
    return (
        state in _DOOR_SEQUENCE_SENT_STATES
        and isinstance(write_count, int)
        and not isinstance(write_count, bool)
        and write_count == DOOR_ONE_SHOT_WRITE_COUNT
        and existing_ctpp_reused is True
    )
