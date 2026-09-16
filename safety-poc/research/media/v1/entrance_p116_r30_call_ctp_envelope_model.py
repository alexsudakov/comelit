"""P116/R30 offline model for the CTP transaction carried inside CTPP.

This module performs no network I/O. It models the framing already visible in
our helper and in the pinned public comelit-vip implementation.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

CTP_VERSION = 0x18
FLAG_SYN = 0xC0
FLAG_DATA = 0x40
FLAG_ACK = 0x00
FLAG_FIN = 0x20
OP_INVITE = 0x0001
OP_MEDIA_REQUEST = 0x0011
TRAILER_MARKER = b"\xff\xff\xff\xff"
LOGADDR_LEN = 10


@dataclass(frozen=True, slots=True)
class CtpEnvelope:
    flags: int
    version: int
    connection: bytes
    sequence: int
    acknowledgement: int
    inner_body: bytes
    source_raw: bytes
    destination_raw: bytes

    @property
    def opcode(self) -> int | None:
        return struct.unpack_from(">H", self.inner_body)[0] if len(self.inner_body) >= 2 else None

    @property
    def is_syn(self) -> bool:
        return bool(self.flags & 0x80)

    @property
    def connection_word(self) -> int:
        return struct.unpack(">H", self.connection)[0]

    @property
    def peer_connection(self) -> bytes:
        return struct.pack(">H", self.connection_word ^ 0x8000)


def parse_ctp_envelope(payload: bytes) -> CtpEnvelope:
    if len(payload) < 32:
        raise ValueError("CTP packet too short")
    if payload[1] != CTP_VERSION:
        raise ValueError("unsupported CTP version")
    inner_len = struct.unpack_from(">H", payload, 6)[0]
    body_end = 8 + inner_len
    trailer_start = body_end + ((-inner_len) % 4)
    if len(payload) != trailer_start + 24:
        raise ValueError("CTP length mismatch")
    trailer = payload[trailer_start:]
    if trailer[:4] != TRAILER_MARKER:
        raise ValueError("bad CTP trailer marker")
    return CtpEnvelope(
        flags=payload[0],
        version=payload[1],
        connection=payload[2:4],
        sequence=payload[4],
        acknowledgement=payload[5],
        inner_body=payload[8:body_end],
        source_raw=trailer[4:14],
        destination_raw=trailer[14:24],
    )


def build_ctp_envelope(
    *,
    flags: int,
    connection: bytes,
    sequence: int,
    acknowledgement: int,
    inner_body: bytes,
    source_raw: bytes,
    destination_raw: bytes,
) -> bytes:
    if len(connection) != 2:
        raise ValueError("connection must be exactly two bytes")
    if len(source_raw) != LOGADDR_LEN or len(destination_raw) != LOGADDR_LEN:
        raise ValueError("logical addresses must be exactly ten bytes")
    if not 0 <= sequence <= 0xFF or not 0 <= acknowledgement <= 0xFF:
        raise ValueError("sequence/acknowledgement must fit in one byte")
    header = struct.pack(
        ">BB2sBBH",
        flags,
        CTP_VERSION,
        connection,
        sequence,
        acknowledgement,
        len(inner_body),
    )
    padding = b"\x00" * (-len(inner_body) % 4)
    return header + inner_body + padding + TRAILER_MARKER + source_raw + destination_raw


def is_inbound_invite(envelope: CtpEnvelope) -> bool:
    return envelope.is_syn and envelope.opcode == OP_INVITE


def build_call_bound_media_packet(
    *,
    local_connection: bytes,
    sequence: int,
    acknowledgement: int,
    mediareq26: bytes,
    source_raw: bytes,
    destination_raw: bytes,
) -> bytes:
    if len(mediareq26) != 26:
        raise ValueError("mediareq26 must be 26 bytes")
    if struct.unpack_from(">H", mediareq26)[0] != OP_MEDIA_REQUEST:
        raise ValueError("mediareq26 must start with OP_MEDIA_REQUEST")
    packet = build_ctp_envelope(
        flags=FLAG_DATA,
        connection=local_connection,
        sequence=sequence,
        acknowledgement=acknowledgement,
        inner_body=mediareq26,
        source_raw=source_raw,
        destination_raw=destination_raw,
    )
    if len(packet) != 60:
        raise AssertionError("26-byte media request must produce a 60-byte CTP packet")
    return packet


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P116 R30 CTP ENVELOPE MODEL ===",
            "OUTER_CTPP_HANDLE_IS_CALL_TRANSACTION=false",
            "INNER_CTP_CONNECTION_OFFSET=2..3",
            "INNER_CTP_SEQUENCE_OFFSET=4",
            "INNER_CTP_ACK_OFFSET=5",
            "INNER_CTP_BODY_LENGTH_OFFSET=6..7",
            "INNER_CTP_BODY_OFFSET=8",
            "MEDIAREQ26_WRAPPED_CTP_PACKET_LENGTH=60",
            "NETWORK_IO=false",
            "LIVE_RUN=NOT_RUN",
            "=== END COMELIT P116 R30 CTP ENVELOPE MODEL ===",
        )
    )
