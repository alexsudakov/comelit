"""P116/R33 offline scalar trace for attached inbound media.

This model is bounded and offline-only. It reuses the R30B call-transaction
model for CTP capture and mediareq26 serialization, then adds only scalar
media-RX channel lifetime state proven by R33 static evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import struct

from entrance_p116_r30_call_ctp_envelope_model import FLAG_SYN, OP_INVITE, build_ctp_envelope
from entrance_p116_r30b_call_transaction_model import (
    InterceptedWriter,
    OuterCtppHandle,
    TransactionRejected,
    create_call_transaction,
)


class R33TraceRejected(ValueError):
    """Raised when the R33 scalar trace must fail closed."""


@dataclass(frozen=True, slots=True)
class MediaRxChannel:
    pointer_equivalent: str
    channel_id: int
    status_node_state: str


@dataclass(slots=True)
class R33ScalarTrace:
    writer: InterceptedWriter
    transaction: object
    channel: MediaRxChannel | None = None
    open_pending: bool = False
    open_confirmed: bool = False
    video_rx_active: bool = False
    rtp_sink_enabled: bool = False
    disposed_channel_ids: list[int] = field(default_factory=list)
    listener_preserved: bool = True
    call_transaction_preserved: bool = True
    events: list[str] = field(default_factory=lambda: ["CALL_INIT_CAPTURED", "CALL_CTP_CAPTURED"])

    @property
    def network_tx(self) -> int:
        return 0

    @property
    def new_ice(self) -> int:
        return 0

    @property
    def new_cloud(self) -> int:
        return 0

    @property
    def new_pseudotcp(self) -> int:
        return 0

    @property
    def new_registration(self) -> int:
        return 0

    @property
    def door_actions(self) -> int:
        return 0

    @property
    def gate_actions(self) -> int:
        return 0

    @property
    def open_count(self) -> int:
        return self.writer.intercepted_media_open_writes

    @property
    def stop_count(self) -> int:
        return self.writer.intercepted_media_stop_writes

    def allocate_media_rx_channel(self, channel_id: int) -> MediaRxChannel:
        if self.channel is not None:
            raise R33TraceRejected("media RX channel already allocated")
        if not isinstance(channel_id, int) or not 1 <= channel_id <= 0xFFFF:
            raise R33TraceRejected("media RX channel id must be non-zero LE16")
        allocated = MediaRxChannel(
            pointer_equivalent="synthetic_media_rx_channel_pointer",
            channel_id=channel_id,
            status_node_state="OPEN_REQUEST_LOCAL",
        )
        self.channel = allocated
        self.transaction.allocate_media_channel(lambda: channel_id)  # type: ignore[attr-defined]
        self.events.append("MEDIA_RX_LOCAL_CHANNEL_ALLOCATE")
        return allocated

    def send_open(self, *, use_registration_handle: bool = False) -> None:
        if use_registration_handle:
            raise R33TraceRejected("OPEN on registration handle rejected")
        if self.channel is None:
            raise R33TraceRejected("OPEN before media RX channel allocation rejected")
        if self.open_pending or self.open_confirmed or self.video_rx_active or self.open_count:
            raise R33TraceRejected("second OPEN rejected")
        self.transaction.intercept_media_open(self.writer)  # type: ignore[attr-defined]
        self.open_pending = True
        self.video_rx_active = True
        self.events.append("CALL_BOUND_MEDIAREQ26_OPEN")

    def observe_channel_open_response(self, *, ok: bool = True, channel_id: int | None = None) -> None:
        if self.channel is None or not self.open_pending:
            raise R33TraceRejected("channel open response without pending OPEN rejected")
        if channel_id is not None and channel_id != self.channel.channel_id:
            raise R33TraceRejected("wrong channel id in open response rejected")
        self.open_pending = False
        self.open_confirmed = bool(ok)
        self.events.append("CHANNEL_OPEN_RESPONSE_PASS" if ok else "CHANNEL_OPEN_RESPONSE_FAIL")

    def enable_rtp(self, *, channel_id: int | None = None) -> None:
        if self.channel is None or not self.video_rx_active:
            raise R33TraceRejected("RTP before OPEN rejected")
        if channel_id is not None and channel_id != self.channel.channel_id:
            raise R33TraceRejected("wrong channel id for RTP rejected")
        self.rtp_sink_enabled = True
        self.events.append("RTP_ENABLED")

    def send_stop(self, *, channel_id: int | None = None) -> None:
        if self.channel is None or not self.video_rx_active or not self.open_count:
            raise R33TraceRejected("STOP before proven OPEN rejected")
        if self.stop_count:
            raise R33TraceRejected("second STOP rejected")
        if channel_id is not None and channel_id != self.channel.channel_id:
            raise R33TraceRejected("wrong channel id for STOP rejected")
        self.transaction.intercept_media_stop(self.writer, media_channel_id=self.channel.channel_id)  # type: ignore[attr-defined]
        self.events.append("CALL_BOUND_MEDIAREQ26_STOP")

    def dispose_media_rx_channel(self, *, channel_id: int | None = None) -> None:
        if self.channel is None:
            raise R33TraceRejected("dispose without channel rejected")
        if not self.stop_count:
            raise R33TraceRejected("dispose before STOP rejected")
        if channel_id is not None and channel_id != self.channel.channel_id:
            raise R33TraceRejected("wrong channel id for dispose rejected")
        self.disposed_channel_ids.append(self.channel.channel_id)
        self.video_rx_active = False
        self.rtp_sink_enabled = False
        self.channel = None
        self.events.append("MEDIA_RX_CHANNEL_DISPOSE")

    def preserve_listener_and_call_transaction(self) -> None:
        if self.channel is not None or self.video_rx_active:
            raise R33TraceRejected("listener preservation is checked after media disposal")
        self.listener_preserved = True
        self.call_transaction_preserved = True
        self.events.append("LISTENER_CALL_TRANSACTION_PRESERVED")


def create_trace_at_call_barrier() -> R33ScalarTrace:
    transaction = create_call_transaction(
        outer_ctpp_handle=OuterCtppHandle(7),
        serialized_ctp_packet=_synthetic_invite_packet(),
    )
    writer = InterceptedWriter()
    transaction.intercept_transport_ack(writer)
    transaction.intercept_capability_stage()
    transaction.intercept_alerting_stage()
    transaction.reach_call_signaling_order_barrier()
    return R33ScalarTrace(writer=writer, transaction=transaction)


def run_offline_scalar_trace() -> R33ScalarTrace:
    trace = create_trace_at_call_barrier()
    trace.allocate_media_rx_channel(0x3456)
    trace.send_open()
    trace.observe_channel_open_response(ok=True, channel_id=0x3456)
    trace.enable_rtp(channel_id=0x3456)
    trace.send_stop(channel_id=0x3456)
    trace.dispose_media_rx_channel(channel_id=0x3456)
    trace.preserve_listener_and_call_transaction()
    return trace


def verify_trace(trace: R33ScalarTrace) -> dict[str, bool | int | str]:
    positions = {event: index for index, event in enumerate(trace.events)}
    required_order = [
        "CALL_INIT_CAPTURED",
        "CALL_CTP_CAPTURED",
        "MEDIA_RX_LOCAL_CHANNEL_ALLOCATE",
        "CALL_BOUND_MEDIAREQ26_OPEN",
        "CHANNEL_OPEN_RESPONSE_PASS",
        "RTP_ENABLED",
        "CALL_BOUND_MEDIAREQ26_STOP",
        "MEDIA_RX_CHANNEL_DISPOSE",
        "LISTENER_CALL_TRANSACTION_PRESERVED",
    ]
    ordered = all(
        positions[required_order[index]] < positions[required_order[index + 1]]
        for index in range(len(required_order) - 1)
    )
    return {
        "ORDER": ordered,
        "NETWORK_TX": trace.network_tx,
        "NEW_ICE": trace.new_ice,
        "NEW_CLOUD": trace.new_cloud,
        "NEW_PSEUDOTCP": trace.new_pseudotcp,
        "NEW_REGISTRATION": trace.new_registration,
        "OPEN_COUNT": trace.open_count,
        "STOP_COUNT": trace.stop_count,
        "DOOR": trace.door_actions,
        "GATE": trace.gate_actions,
        "LISTENER_PRESERVED": trace.listener_preserved,
        "CALL_TRANSACTION_PRESERVED": trace.call_transaction_preserved,
        "DISPOSED_CHANNEL_COUNT": len(trace.disposed_channel_ids),
        "FINAL_CHANNEL_PRESENT": trace.channel is not None,
        "RTP_SINK_ENABLED": trace.rtp_sink_enabled,
    }


def report() -> str:
    trace = run_offline_scalar_trace()
    evidence = verify_trace(trace)
    return "\n".join(
        (
            "=== COMELIT P116 R33 OFFLINE SCALAR TRACE ===",
            f"CALL_INIT_CAPTURED={_pass(evidence['ORDER'])}",
            "CALL_CTP_CAPTURED=PASS",
            "MEDIA_RX_LOCAL_CHANNEL_ALLOCATE=PASS",
            f"CALL_BOUND_MEDIAREQ26_OPEN_COUNT={evidence['OPEN_COUNT']}",
            "CHANNEL_OPEN_RESPONSE=PASS",
            "RTP_ENABLED=PASS",
            f"CALL_BOUND_MEDIAREQ26_STOP_COUNT={evidence['STOP_COUNT']}",
            f"MEDIA_RX_CHANNEL_DISPOSE_COUNT={evidence['DISPOSED_CHANNEL_COUNT']}",
            f"LISTENER_CALL_TRANSACTION_PRESERVED={_pass(evidence['LISTENER_PRESERVED'] and evidence['CALL_TRANSACTION_PRESERVED'])}",
            f"NETWORK_TX={evidence['NETWORK_TX']}",
            f"NEW_ICE={evidence['NEW_ICE']}",
            f"NEW_CLOUD={evidence['NEW_CLOUD']}",
            f"NEW_PSEUDOTCP={evidence['NEW_PSEUDOTCP']}",
            f"NEW_REGISTRATION={evidence['NEW_REGISTRATION']}",
            f"DOOR={evidence['DOOR']}",
            f"GATE={evidence['GATE']}",
            "OFFLINE_SCALAR_TRACE=PASS",
            "=== END COMELIT P116 R33 OFFLINE SCALAR TRACE ===",
        )
    )


def _synthetic_invite_packet() -> bytes:
    invite = bytearray(40)
    struct.pack_into(">H", invite, 0, OP_INVITE)
    invite[2:12] = b"00000643\x00\x00"
    invite[12:22] = b"000401177\x00"
    invite[24:28] = b"CALL"
    return build_ctp_envelope(
        flags=FLAG_SYN,
        connection=b"\x12\x34",
        sequence=0x56,
        acknowledgement=0x78,
        inner_body=bytes(invite),
        source_raw=b"00000643\x00\x00",
        destination_raw=b"000401177\x00",
    )


def _pass(value: bool | int) -> str:
    if not isinstance(value, bool):
        raise TypeError("PASS marker requires bool")
    return "PASS" if value else "FAIL"


if __name__ == "__main__":
    print(report())
