#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys

CANONICAL_ROOT = Path("/root/comelit-vip-poc")
PINNED = {
    "comelit_vip/application_session.py": "7c30aab9bd03917e0e84fb9b31f924f95eabeb8edd6a1fe74d4e4f012c2145fd",
    "comelit_vip/channel_session.py": "b34d87c382ea601d96761f59a31e62aa2d1e959ea9c24e99a63964e1c033e1d1",
    "comelit_vip/control_codec.py": "e89e3fe20b24ef2f22ceaa15b186b4db7f71f5f48c7f5aeaf6a07f38bea854a2",
    "comelit_vip/transport.py": "21ce339f15d44216baecdeefa19490a5d5632f689155d628b76d4abb7872a0d4",
    "comelit_vip/vip_codec.py": "4ebf41833977e198b1ef94f4aace37f86dad9fbaec08c716242b9ee40437859a",
    "comelit_vip/vip_session.py": "35b604372e9bd42a6631d0c923ac99d49e02e4b7c8892360633eedc23425dc39",
}

SYNTHETIC_TOKEN = "0123456789abcdef0123456789abcdef"
UAUT_REQUESTED_CHANNEL = 7449
UCFG_REQUESTED_CHANNEL = 7450
AUTH_MESSAGE_ID = 5
UCFG_MESSAGE_ID = 6
UCFG_ADDRESSBOOKS = "none"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_pins(root: Path) -> None:
    for rel, expected in PINNED.items():
        actual = sha256_file(root / rel)
        if actual != expected:
            raise RuntimeError(f"canonical pin mismatch for {rel}: {actual}")


def predicted_control_packet(*, opcode: int, channel_id: int, channel_name: bytes | None = None) -> bytes:
    if opcode == 1:
        if channel_name is None or len(channel_name) != 4:
            raise ValueError("open request requires a four-byte channel name")
        body = bytearray(15)
        body[0:2] = (0xABCD).to_bytes(2, "little")
        body[2:4] = (1).to_bytes(2, "little")
        body[4:8] = (7).to_bytes(4, "little")
        body[8:12] = channel_name
        body[12:14] = channel_id.to_bytes(2, "little")
        body[14] = 0
    elif opcode == 3:
        body = bytearray(10)
        body[0:2] = (0xABCD).to_bytes(2, "little")
        body[2:4] = (3).to_bytes(2, "little")
        body[4:8] = (2).to_bytes(4, "little")
        body[8:10] = channel_id.to_bytes(2, "little")
    else:
        raise ValueError("unsupported predicted control opcode")

    packet = bytearray(8 + len(body))
    packet[0:2] = b"\x00\x06"
    packet[2:4] = len(body).to_bytes(2, "little")
    packet[4:8] = (0).to_bytes(4, "little")
    packet[8:] = body
    return bytes(packet)


class CapturedWrite(RuntimeError):
    def __init__(self, packet: bytes):
        super().__init__("captured canonical write")
        self.packet = packet


class CaptureTransport:
    async def read(self, max_bytes: int = 4096) -> bytes:
        raise EOFError("capture transport has no inbound data")

    async def write(self, data: bytes) -> None:
        raise CapturedWrite(bytes(data))

    async def close(self) -> None:
        return None


async def capture_application_requests(root: Path) -> tuple[bytes, bytes]:
    root_s = str(root)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)

    from comelit_vip.application_session import VipApplicationSession
    from comelit_vip.channel_session import ChannelState
    from comelit_vip.vip_session import VipSession

    class FakeChannels:
        def __init__(self) -> None:
            self.session = VipSession(CaptureTransport())
            self.states: dict[int, ChannelState] = {}

        async def open_channel(self, channel_name: str, *args, **kwargs):
            channel_id = UAUT_REQUESTED_CHANNEL if channel_name == "UAUT" else UCFG_REQUESTED_CHANNEL
            state = ChannelState(
                channel_name=channel_name,
                channel_id=channel_id,
                channel_flag=0,
                origin="local",
                open_response_word=0,
            )
            self.states[channel_id] = state
            return state

        async def close_channel(self, channel_id: int):
            self.states.pop(channel_id, None)
            return None

        def get_channel(self, channel_id: int):
            return self.states.get(channel_id)

    channels = FakeChannels()
    app = VipApplicationSession(channels)

    try:
        await app.authenticate(
            SYNTHETIC_TOKEN,
            message_id=AUTH_MESSAGE_ID,
        )
    except CapturedWrite as exc:
        auth_packet = exc.packet
    else:
        raise RuntimeError("canonical authenticate produced no captured write")

    ucfg_state = ChannelState(
        channel_name="UCFG",
        channel_id=UCFG_REQUESTED_CHANNEL,
        channel_flag=0,
        origin="local",
        open_response_word=0,
    )
    channels.states[UCFG_REQUESTED_CHANNEL] = ucfg_state

    try:
        await app.get_configuration(
            ucfg_state,
            message_id=UCFG_MESSAGE_ID,
            addressbooks=UCFG_ADDRESSBOOKS,
        )
    except CapturedWrite as exc:
        ucfg_packet = exc.packet
    else:
        raise RuntimeError("canonical get_configuration produced no captured write")

    return auth_packet, ucfg_packet


def decode_vip_packet(packet: bytes) -> tuple[int, bytes]:
    if len(packet) < 8 or packet[:2] != b"\x00\x06":
        raise RuntimeError("unexpected canonical ViP frame header")
    body_len = int.from_bytes(packet[2:4], "little")
    if len(packet) != 8 + body_len:
        raise RuntimeError("canonical ViP frame length mismatch")
    request_id = int.from_bytes(packet[4:8], "little")
    return request_id, packet[8:]


async def derive(root: Path) -> dict[str, object]:
    verify_pins(root)

    root_s = str(root)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)

    from comelit_vip.control_codec import CloseChannelRequest, OpenChannelRequest, encode_control_message
    from comelit_vip.vip_codec import encode_frame

    auth_packet, ucfg_packet = await capture_application_requests(root)
    auth_request_id, auth_body = decode_vip_packet(auth_packet)
    ucfg_request_id, ucfg_body = decode_vip_packet(ucfg_packet)

    expected_auth = (
        '{"message":"access","user-token":"'
        + SYNTHETIC_TOKEN
        + '","message-type":"request","message-id":'
        + str(AUTH_MESSAGE_ID)
        + "}\n"
    ).encode("utf-8")
    if auth_request_id != UAUT_REQUESTED_CHANNEL:
        raise RuntimeError("canonical authenticate request_id mismatch")
    if auth_body != expected_auth:
        raise RuntimeError("canonical authenticate body no longer matches capture-derived contract")
    if not auth_body.endswith(b"\n") or auth_body.endswith(b"\\n"):
        raise RuntimeError("canonical authenticate body does not end with real LF")

    if ucfg_request_id != UCFG_REQUESTED_CHANNEL:
        raise RuntimeError("canonical UCFG request_id mismatch")
    if not ucfg_body.endswith(b"\n"):
        raise RuntimeError("canonical UCFG request does not end with LF")
    if b"get-configuration" not in ucfg_body:
        raise RuntimeError("canonical UCFG request is not get-configuration")
    if any(token in ucfg_body for token in (b"CTPP", b"OPEN_DOOR", b"open_door", b"create_door_message")):
        raise RuntimeError("canonical UCFG request contains forbidden actuator surface")

    canonical_close_uaut = encode_frame(
        0,
        encode_control_message(CloseChannelRequest(channel_id=UAUT_REQUESTED_CHANNEL)),
    )
    canonical_open_ucfg = encode_frame(
        0,
        encode_control_message(
            OpenChannelRequest(
                channel_name="UCFG",
                channel_id=UCFG_REQUESTED_CHANNEL,
                channel_flag=0,
            )
        ),
    )
    canonical_close_ucfg = encode_frame(
        0,
        encode_control_message(CloseChannelRequest(channel_id=UCFG_REQUESTED_CHANNEL)),
    )

    predicted_close_uaut = predicted_control_packet(opcode=3, channel_id=UAUT_REQUESTED_CHANNEL)
    predicted_open_ucfg = predicted_control_packet(
        opcode=1,
        channel_id=UCFG_REQUESTED_CHANNEL,
        channel_name=b"UCFG",
    )
    predicted_close_ucfg = predicted_control_packet(opcode=3, channel_id=UCFG_REQUESTED_CHANNEL)

    if canonical_close_uaut != predicted_close_uaut:
        raise RuntimeError("predicted CLOSE UAUT packet does not match canonical codec")
    if canonical_open_ucfg != predicted_open_ucfg:
        raise RuntimeError("predicted OPEN UCFG packet does not match canonical codec")
    if canonical_close_ucfg != predicted_close_ucfg:
        raise RuntimeError("predicted CLOSE UCFG packet does not match canonical codec")

    return {
        "schema": 1,
        "canonical_pins": PINNED,
        "auth_request_id": auth_request_id,
        "auth_body_len": len(auth_body),
        "auth_body_sha256": hashlib.sha256(auth_body).hexdigest(),
        "auth_real_lf": True,
        "ucfg_request_id": ucfg_request_id,
        "ucfg_body_hex": ucfg_body.hex(),
        "ucfg_body_len": len(ucfg_body),
        "ucfg_body_sha256": hashlib.sha256(ucfg_body).hexdigest(),
        "close_uaut_packet_sha256": hashlib.sha256(canonical_close_uaut).hexdigest(),
        "open_ucfg_packet_sha256": hashlib.sha256(canonical_open_ucfg).hexdigest(),
        "close_ucfg_packet_sha256": hashlib.sha256(canonical_close_ucfg).hexdigest(),
        "actuator_surface_present": False,
        "network_action_performed": False,
        "secret_value_read": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Derive public-safe P12 protocol templates from pinned canonical code")
    parser.add_argument("--canonical-root", type=Path, default=CANONICAL_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = asyncio.run(derive(args.canonical_root))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print("P12_CANONICAL_TEMPLATE_DERIVATION=PASS")
    print(f"P12_AUTH_BODY_LEN={result['auth_body_len']}")
    print(f"P12_AUTH_BODY_SHA256={result['auth_body_sha256']}")
    print("P12_AUTH_REAL_LF=true")
    print(f"P12_UCFG_BODY_LEN={result['ucfg_body_len']}")
    print(f"P12_UCFG_BODY_SHA256={result['ucfg_body_sha256']}")
    print("P12_CONTROL_TEMPLATE_EQUIVALENCE=PASS")
    print("SECRETS_READ=false")
    print("NETWORK_ACTION_PERFORMED=false")
    print("ACTUATOR_COMMAND_ATTEMPTED=false")
    print("PHYSICAL_DOOR_ACTION=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
