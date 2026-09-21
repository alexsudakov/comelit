#!/usr/bin/env python3
"""P116/R55 region-source observability corrective verifier.

The R55 corrective is intentionally integrated into the R45/R54 region sources.
This helper performs offline gates over those regions; it does not patch
generated C and does not rebuild or promote a native helper.
"""

from __future__ import annotations

import argparse

import entrance_p116_r45_call_adoption_core as r45
import entrance_p116_r54_call_adoption_listener_transform as r54


def verify_region_sources() -> None:
    r45_region = r45.CORE_REGION
    r54_region = r54.R54_REGION

    required_r45 = (
        "unsigned peer_data_ack_count;",
        'state->peer_data_ack_count += 1u;',
        '"CALL_PEER_DATA_ACK"',
    )
    for needle in required_r45:
        if needle not in r45_region:
            raise RuntimeError(f"R55_R45_REGION_GATE=FAIL missing={needle}")

    if "state->r45.inbound_ack_count > 0u" in r54_region:
        raise RuntimeError("R55_R54_PEER_ACK_COUNTER_GATE=FAIL")

    required_r54 = (
        "R54_DIAGNOSTICS_PHASE=%s",
        "R54_DIAGNOSTICS_LOCAL_AFTER_TRIO",
        "R54_DIAGNOSTICS_AFTER_PEER_CAPABILITIES",
        "R54_DIAGNOSTICS_GENERATION_END",
        "R54_PEER_CAPABILITIES_SEEN=NOT_REACHED",
        "R54_PEER_WAIT_ENDED_WITHOUT_CAPABILITIES=%s",
        "state->r45.peer_data_ack_count > 0u",
    )
    for needle in required_r54:
        if needle not in r54_region:
            raise RuntimeError(f"R55_R54_REGION_GATE=FAIL missing={needle}")


def report() -> str:
    verify_region_sources()
    return "\n".join(
        (
            "=== P116 R55 REGION-SOURCE OBSERVABILITY CORRECTIVE ===",
            "CORRECTIVE_TARGET=REGION_SOURCES",
            "GENERATED_TEXT_PATCH=false",
            "PUBLICATION_PHASE_DISCRIMINATOR_ADDED=true",
            "PEER_SCOPE_FIELDS_GATED_FROM_LOCAL_PHASE=true",
            "PEER_WAIT_TERMINAL_MARKER_ADDED=true",
            "PEER_DATA_ACK_COUNTER_FIXED=true",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END P116 R55 REGION-SOURCE OBSERVABILITY CORRECTIVE ===",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args(argv)
    print(report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
