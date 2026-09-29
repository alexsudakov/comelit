from __future__ import annotations

DOOR_ONE_SHOT_WRITE_COUNT = 5
CALL_TIME_DOOR_WRITE_COUNT = 1
CALL_TIME_DOOR_PATH = "CALL_TIME_SINGLE"
_DOOR_SEQUENCE_SENT_STATES = frozenset({"ACKED", "UNKNOWN_OUTCOME"})


def door_one_shot_sequence_sent(
    *,
    state: object,
    write_count: object,
    existing_ctpp_reused: object,
    door_path: object = None,
    call_time_sequence_committed: object = None,
) -> bool:
    """Return whether one validated Door TX profile left HA locally.

    This is deliberately weaker than protocol acknowledgement and must never be
    used to assert a physical door effect.

    Standalone Door requires all five validated persistent-CTPP writes.
    Active-call Entrance Door uses the separately validated CALL_TIME_SINGLE
    profile: one frame on the existing call transaction, with proof that the
    saved call sequence was still current when TX completed.
    """
    if (
        not isinstance(state, str)
        or state not in _DOOR_SEQUENCE_SENT_STATES
        or not isinstance(write_count, int)
        or isinstance(write_count, bool)
        or existing_ctpp_reused is not True
    ):
        return False

    if door_path is None:
        return write_count == DOOR_ONE_SHOT_WRITE_COUNT

    if door_path == CALL_TIME_DOOR_PATH:
        return (
            write_count == CALL_TIME_DOOR_WRITE_COUNT
            and call_time_sequence_committed is True
        )

    return False
