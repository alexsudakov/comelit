from pathlib import Path


RUNNER = Path(
    "safety-poc/research/media/v1/ct120_run_entrance_self_activation_signaling_probe.sh"
)
LAUNCHER_V3 = Path(
    "safety-poc/research/media/v1/ct120_launch_entrance_self_activation_signaling_probe_v3.sh"
)


def test_v3_patch_matches_pinned_p30_runner_and_relaxes_only_false_door_invariant():
    runner = RUNNER.read_text(encoding="utf-8")
    launcher = LAUNCHER_V3.read_text(encoding="utf-8")

    assert "BASE_RUNNER_BLOB=399db88970197d63f424262cfbde38d9253d816a" in launcher
    assert "AUTOMATIC_RETRY=false" in launcher

    old_timer = (
        "if grep -Fq $'        100,\\n        v4_door_tick_cb,' "
        '"$CANDIDATE_SOURCE"; then'
    )
    new_timer = "if grep -Fq '        v4_door_tick_cb,' \"$CANDIDATE_SOURCE\"; then"

    old_live_gate = '''    if [ "$COUNT" -ne 1 ]; then
        LIVE_GATE=FAIL
    fi
done
'''
    new_live_gate = '''    if [ "$marker" = 'ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false' ]; then
        if [ "$COUNT" -lt 1 ]; then
            LIVE_GATE=FAIL
        fi
    elif [ "$COUNT" -ne 1 ]; then
        LIVE_GATE=FAIL
    fi
done
'''

    assert runner.count(old_timer) == 1
    assert runner.count(old_live_gate) == 1

    patched = runner.replace(old_timer, new_timer, 1)
    patched = patched.replace(old_live_gate, new_live_gate, 1)

    assert old_timer not in patched
    assert patched.count(new_timer) == 1
    assert old_live_gate not in patched
    assert patched.count(new_live_gate) == 1

    # Event markers remain exactly-once. Only the immutable negative Door
    # safety assertion is permitted to repeat, because multiple identical
    # `false` observations do not represent multiple actions.
    assert "if [ \"$marker\" = 'ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false' ]; then" in patched
    assert 'if [ "$COUNT" -lt 1 ]; then' in patched
    assert 'elif [ "$COUNT" -ne 1 ]; then' in patched

    required_event_markers = (
        "ENTRANCE_SELF_ACTIVATION_SENT=PASS",
        "ENTRANCE_SELF_ACTIVATION_ACK=PASS",
        "ENTRANCE_VIDEO_EVENT_SENT=PASS",
        "ENTRANCE_VIDEO_EVENT_ACK=PASS",
        "ENTRANCE_DEVICE_VIDEO_EVENT=PASS",
        "ENTRANCE_SIGNALING_PROBE_RESULT=PASS",
        "PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false",
        "PSEUDOTCP_GRACEFUL_CLOSE_FORCE_RST_SENT=false",
    )
    for marker in required_event_markers:
        assert marker in patched
