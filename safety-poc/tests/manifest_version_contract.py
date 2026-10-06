import re


_RELEASE_VERSION_RE = re.compile(
    r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?P<suffix>[A-Za-z][A-Za-z0-9.\-]*)?$"
)


def release_tuple(value: str) -> tuple[int, int, int]:
    match = _RELEASE_VERSION_RE.fullmatch(value)
    if not match:
        raise ValueError(f"invalid release version: {value!r}")
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
    )


def is_valid_release_version(value: str) -> bool:
    try:
        release_tuple(value)
    except ValueError:
        return False
    return True
