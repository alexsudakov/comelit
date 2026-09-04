#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import shlex
import sys
import urllib.error
import urllib.request


ENDPOINT = (
    "https://api.comelitgroup.com/"
    "servicerest/p2p/start"
)

SECRETS = Path(
    "/root/.config/comelit/secrets.env"
)


def read_env() -> dict[str, str]:
    result: dict[str, str] = {}

    for raw in SECRETS.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines():

        line = raw.strip()

        if (
            not line
            or line.startswith("#")
            or "=" not in line
        ):
            continue

        key, value = line.split(
            "=",
            1,
        )

        key = key.strip()
        value = value.strip()

        try:
            parts = shlex.split(
                value,
                posix=True,
            )
        except ValueError:
            parts = [value]

        if len(parts) == 1:
            value = parts[0]

        result[key] = value

    return result


def sdp_metadata(
    prefix: str,
    sdp: str,
) -> None:

    lines = [
        line.strip()
        for line in sdp.replace(
            "\r\n",
            "\n",
        ).split("\n")
        if line.strip()
    ]

    candidates = [
        line
        for line in lines
        if line.startswith(
            "a=candidate:"
        )
    ]

    ufrag = [
        line
        for line in lines
        if line.startswith(
            "a=ice-ufrag:"
        )
    ]

    pwd = [
        line
        for line in lines
        if line.startswith(
            "a=ice-pwd:"
        )
    ]

    candidate_types = []

    for line in candidates:
        fields = line.split()

        try:
            idx = fields.index("typ")

            if idx + 1 < len(fields):
                candidate_types.append(
                    fields[idx + 1]
                )
        except ValueError:
            pass

    print(
        f"{prefix}_SDP_LINES="
        f"{len(lines)}"
    )

    print(
        f"{prefix}_CANDIDATE_COUNT="
        f"{len(candidates)}"
    )

    print(
        f"{prefix}_CANDIDATE_TYPES="
        + (
            ",".join(
                sorted(
                    set(candidate_types)
                )
            )
            if candidate_types
            else "NONE"
        )
    )

    print(
        f"{prefix}_UFRAG_PRESENT="
        + str(
            bool(ufrag)
        ).lower()
    )

    if ufrag:
        value = ufrag[0].split(
            ":",
            1,
        )[1]

        print(
            f"{prefix}_UFRAG_LENGTH="
            f"{len(value)}"
        )

    print(
        f"{prefix}_PWD_PRESENT="
        + str(
            bool(pwd)
        ).lower()
    )

    if pwd:
        value = pwd[0].split(
            ":",
            1,
        )[1]

        print(
            f"{prefix}_PWD_LENGTH="
            f"{len(value)}"
        )

    attrs = {
        "ICE_ROLE":
            "a=ice-role:",

        "NEGO_WAIT":
            "a=nego-wait:",

        "COMELIT_LEGACY_SESSION":
            "a=comelit-legacy-session:",

        "COMELIT_SESSION_ID":
            "a=comelit-session-id:",

        "COMELIT_NEGO_AGGRESSIVE":
            "a=comelit-nego-aggressive:",
    }

    for name, marker in attrs.items():
        present = any(
            line.startswith(marker)
            for line in lines
        )

        print(
            f"{prefix}_{name}_PRESENT="
            + str(present).lower()
        )


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "offer",
        type=Path,
    )

    parser.add_argument(
        "remote",
        type=Path,
    )

    args = parser.parse_args()

    env = read_env()

    required = (
        "COMELIT_DUUID",
        "COMELIT_VIP_TOKEN",
        "COMELIT_OAUTH_ACCESS_TOKEN",
    )

    missing = [
        key
        for key in required
        if not env.get(key)
    ]

    if missing:
        print(
            "CREDENTIAL_GATE=FAIL"
        )

        print(
            "MISSING_KEYS="
            + ",".join(missing)
        )

        return 10

    print(
        "CREDENTIAL_GATE=PASS"
    )

    offer = args.offer.read_text(
        encoding="utf-8",
    )

    print()
    print(
        "=== LOCAL SDP METADATA ==="
    )

    sdp_metadata(
        "LOCAL",
        offer,
    )

    encoded_sdp = (
        base64.b64encode(
            offer.encode("utf-8")
        ).decode("ascii")
    )

    payload = {
        "deviceUuid":
            env["COMELIT_DUUID"],

        "data": {
            "authMode":
                "user_viper_token",

            "secret":
                env["COMELIT_VIP_TOKEN"],

            "timeout":
                10,

            "sdp":
                encoded_sdp,
        },

        "protocol": {
            "name":
                "viper_p2p_v2",

            "version":
                1,
        },
    }

    body = json.dumps(
        payload,
        separators=(",", ":"),
    ).encode("utf-8")

    request = urllib.request.Request(
        ENDPOINT,
        method="POST",
        data=body,
        headers={
            "Authorization":
                "bearer "
                + env[
                    "COMELIT_OAUTH_ACCESS_TOKEN"
                ],

            "Content-Type":
                "application/json",

            "Accept":
                "application/json",
        },
    )

    print()
    print(
        "=== CLOUD REQUEST ==="
    )

    print(
        "P2P_ENDPOINT="
        + ENDPOINT
    )

    print(
        "P2P_PROTOCOL=viper_p2p_v2/1"
    )

    print(
        "P2P_AUTH_MODE=user_viper_token"
    )

    print(
        "HTTP_AUTH=bearer"
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=20,
        ) as response:

            status = response.status
            raw = response.read()

    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read()

    except Exception as exc:
        print(
            "P2P_HTTP_EXCEPTION="
            + exc.__class__.__name__
        )

        return 11

    print(
        f"P2P_HTTP_STATUS={status}"
    )

    try:
        obj = json.loads(
            raw.decode(
                "utf-8",
                errors="replace",
            )
        )

    except Exception:
        print(
            "P2P_RESPONSE_JSON=false"
        )

        print(
            "P2P_RESPONSE_BYTES="
            + str(len(raw))
        )

        return 12

    print(
        "P2P_RESPONSE_JSON=true"
    )

    if isinstance(
        obj,
        dict,
    ):
        print(
            "P2P_RESPONSE_KEYS="
            + ",".join(
                sorted(obj.keys())
            )
        )

        result = obj.get(
            "result"
        )

        if result is None:
            print(
                "P2P_RESULT_PRESENT=false"
            )

        elif isinstance(
            result,
            (str, int, float, bool),
        ):
            print(
                "P2P_RESULT_PRESENT=true"
            )

            print(
                "P2P_RESULT_TYPE="
                + type(result).__name__
            )

            print(
                "P2P_RESULT="
                + str(result)[:160]
            )

        elif isinstance(
            result,
            dict,
        ):
            print(
                "P2P_RESULT_PRESENT=true"
            )

            print(
                "P2P_RESULT_TYPE=dict"
            )

            print(
                "P2P_RESULT_KEYS="
                + ",".join(
                    sorted(result.keys())
                )
            )

            for key in (
                "status",
                "code",
                "success",
                "error",
            ):
                if key in result:
                    print(
                        "P2P_RESULT_"
                        + key.upper()
                        + "="
                        + str(result[key])[:160]
                    )

        else:
            print(
                "P2P_RESULT_PRESENT=true"
            )

            print(
                "P2P_RESULT_TYPE="
                + type(result).__name__
            )

    if status < 200 or status >= 300:
        if isinstance(
            obj,
            dict,
        ):
            for key in (
                "error",
                "status",
                "title",
                "type",
            ):
                if key in obj:
                    print(
                        "P2P_"
                        + key.upper()
                        + "="
                        + str(obj[key])[:160]
                    )

        print(
            "P2P_CLOUD_NEGOTIATION=FAIL"
        )

        return 13

    if not isinstance(
        obj,
        dict,
    ):
        print(
            "P2P_RESPONSE_OBJECT=false"
        )

        return 14

    data = obj.get(
        "data"
    )

    if not isinstance(
        data,
        dict,
    ):
        print(
            "P2P_DATA_OBJECT=false"
        )

        return 15

    encoded_remote = data.get(
        "sdp"
    )

    if not isinstance(
        encoded_remote,
        str,
    ) or not encoded_remote:

        print(
            "REMOTE_SDP_PRESENT=false"
        )

        print(
            "P2P_CLOUD_NEGOTIATION=FAIL"
        )

        return 16

    try:
        remote_bytes = (
            base64.b64decode(
                encoded_remote,
                validate=True,
            )
        )

        remote = remote_bytes.decode(
            "utf-8"
        )

    except Exception:
        print(
            "REMOTE_SDP_DECODE=FAIL"
        )

        return 17

    args.remote.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    args.remote.write_text(
        remote,
        encoding="utf-8",
    )

    os.chmod(
        args.remote,
        0o600,
    )

    print(
        "REMOTE_SDP_PRESENT=true"
    )

    print(
        "REMOTE_SDP_BYTES="
        + str(
            len(remote_bytes)
        )
    )

    print(
        "REMOTE_SDP_FILE_MODE=600"
    )

    print()
    print(
        "=== REMOTE SDP METADATA ==="
    )

    sdp_metadata(
        "REMOTE",
        remote,
    )

    remote_lines = [
        line.strip()
        for line in remote.replace(
            "\r\n",
            "\n",
        ).split("\n")
        if line.strip()
    ]

    has_ufrag = any(
        line.startswith(
            "a=ice-ufrag:"
        )
        for line in remote_lines
    )

    has_pwd = any(
        line.startswith(
            "a=ice-pwd:"
        )
        for line in remote_lines
    )

    has_candidate = any(
        line.startswith(
            "a=candidate:"
        )
        for line in remote_lines
    )

    usable = (
        has_ufrag
        and has_pwd
        and has_candidate
    )

    print()
    print(
        "REMOTE_SDP_USABLE="
        + str(usable).lower()
    )

    if not usable:
        print(
            "P2P_CLOUD_NEGOTIATION="
            "INCOMPLETE"
        )

        return 18

    print(
        "P2P_CLOUD_NEGOTIATION=PASS"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
