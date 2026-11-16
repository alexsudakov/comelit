#!/usr/bin/env python3
"""Verify the repository's file-based HACS requirements without a network."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]
DOMAIN = "comelit"
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[a-z]+[0-9]+)?$")

HACS_ALLOWED_KEYS = {
    "content_in_root",
    "country",
    "filename",
    "hacs",
    "hide_default_branch",
    "homeassistant",
    "persistent_directory",
    "render_readme",
    "zip_release",
    "name",
}
HACS_BOOL_KEYS = {
    "content_in_root",
    "hide_default_branch",
    "render_readme",
    "zip_release",
}
HACS_STRING_KEYS = {
    "country",
    "filename",
    "hacs",
    "homeassistant",
    "persistent_directory",
}

CATEGORIES = frozenset(
    """
    ai_voice ai_voice.ai_models ai_voice.image_recognition ai_voice.speech
    ai_voice.voice_assistants appliances_cleaning appliances_cleaning.cleaning
    appliances_cleaning.cooking appliances_cleaning.laundry blinds_curtains
    buttons_remotes climate climate.air_purifiers_humidifiers
    climate.fans_ventilation climate.heat_pumps_air_conditioning
    climate.thermostats_heating climate.water_heaters computers_network
    computers_network.cloud_developer_tools computers_network.monitoring
    computers_network.nas_servers computers_network.printers
    computers_network.routers_network diy_makers diy_makers.boards_hardware
    diy_makers.web_data_connectors energy energy.backup_power
    energy.energy_prices energy.ev_charging energy.meters_monitoring
    energy.solar_batteries finance garden_plants health_wellbeing helpers
    helpers.calculate_value helpers.store_value hubs_protocols
    hubs_protocols.building_automation hubs_protocols.smart_home_hubs
    hubs_protocols.wireless_protocols lighting lighting.bulbs_lamps
    lighting.led_strips_controllers lighting.lighting_systems local_services
    media_entertainment media_entertainment.gaming
    media_entertainment.music_radio_services media_entertainment.speakers_audio
    media_entertainment.tv_streaming messaging_notifications
    messaging_notifications.chat_apps messaging_notifications.email_sms_calls
    messaging_notifications.push_notifications news_social_media
    other_ecosystems pets plugs_switches presence_location
    presence_location.network_presence presence_location.phones_companion_apps
    presence_location.trackers productivity_information
    productivity_information.calendars_todos
    productivity_information.documents_photos
    productivity_information.shopping_groceries security_safety
    security_safety.alarm_systems security_safety.cameras
    security_safety.doorbells_intercoms security_safety.locks_access
    security_safety.smoke_co_alarms sensors sensors.air_quality
    sensors.door_window sensors.motion_presence sensors.temperature_humidity
    vehicles_transport vehicles_transport.bikes_scooters
    vehicles_transport.cars_evs vehicles_transport.flights
    vehicles_transport.public_transport water water.meters_leak_detection
    water.pools_spas water.water_treatment weather_alerts
    weather_alerts.air_quality_pollen weather_alerts.forecasts
    weather_alerts.public_warnings
    """.split()
)


class CheckFailure(Exception):
    """A closed verification failure with a stable machine-readable reason."""


def load_object(path: Path, prefix: str) -> dict[str, object]:
    if not path.is_file():
        raise CheckFailure(f"{prefix}-missing")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise CheckFailure(f"{prefix}-invalid-json") from None
    if not isinstance(value, dict):
        raise CheckFailure(f"{prefix}-not-object")
    return value


def check_information() -> None:
    names = {"readme", "readme.md", "info", "info.md"}
    try:
        found = any(
            entry.is_file() and entry.name.lower() in names for entry in ROOT.iterdir()
        )
    except OSError:
        found = False
    if not found:
        raise CheckFailure("information-missing")


def check_hacsjson() -> None:
    data = load_object(ROOT / "hacs.json", "hacsjson")
    unknown = sorted(set(data) - HACS_ALLOWED_KEYS)
    if unknown:
        raise CheckFailure(f"hacsjson-unknown-key:{unknown[0]}")
    if not isinstance(data.get("name"), str) or not data["name"].strip():
        raise CheckFailure("hacsjson-name-invalid")
    for key in sorted(HACS_BOOL_KEYS):
        if key in data and not isinstance(data[key], bool):
            raise CheckFailure(f"hacsjson-{key}-not-bool")
    for key in sorted(HACS_STRING_KEYS):
        if key in data and not isinstance(data[key], str):
            raise CheckFailure(f"hacsjson-{key}-not-string")
    if data.get("zip_release") is True and not data.get("filename", "").strip():
        raise CheckFailure("hacsjson-zip-release-filename-missing")
    if data.get("content_in_root") is True:
        raise CheckFailure("hacsjson-content-in-root")


def valid_http_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def check_integration_manifest() -> None:
    data = load_object(
        ROOT / "custom_components" / DOMAIN / "manifest.json", "manifest"
    )
    codeowners = data.get("codeowners")
    if not isinstance(codeowners, list) or not codeowners or any(
        not isinstance(owner, str) or not owner.strip() for owner in codeowners
    ):
        raise CheckFailure("manifest-codeowners-invalid")
    for key in ("documentation", "issue_tracker"):
        if not valid_http_url(data.get(key)):
            raise CheckFailure(f"manifest-{key}-invalid")
    if data.get("domain") != DOMAIN:
        raise CheckFailure("manifest-domain-invalid")
    if not isinstance(data.get("name"), str) or not data["name"].strip():
        raise CheckFailure("manifest-name-invalid")
    version = data.get("version")
    if not isinstance(version, str) or VERSION_RE.fullmatch(version) is None:
        raise CheckFailure("manifest-version-invalid")
    if "categories" in data:
        categories = data["categories"]
        if (
            not isinstance(categories, list)
            or not 1 <= len(categories) <= 3
            or any(not isinstance(category, str) for category in categories)
            or len(set(categories)) != len(categories)
            or any(category not in CATEGORIES for category in categories)
        ):
            raise CheckFailure("manifest-categories-invalid")


def check_layout() -> None:
    base = ROOT / "custom_components" / DOMAIN
    for relative in ("__init__.py", "manifest.json", "strings.json", "translations/en.json"):
        if not (base / relative).is_file():
            raise CheckFailure(f"layout-missing:custom_components/{DOMAIN}/{relative}")


def check_license() -> None:
    candidates = ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING")
    path = next((ROOT / name for name in candidates if (ROOT / name).is_file()), None)
    if path is None:
        raise CheckFailure("license-file-missing")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise CheckFailure("license-unrecognized") from None
    markers = (
        "mit license",
        "apache license",
        "bsd 3-clause",
        "bsd 2-clause",
        "gnu general public license",
        "mozilla public license",
    )
    if not text or not any(marker in text[:2000].lower() for marker in markers):
        raise CheckFailure("license-unrecognized")


def main() -> int:
    checks = (
        ("information", check_information),
        ("hacsjson", check_hacsjson),
        ("integration_manifest", check_integration_manifest),
        ("layout", check_layout),
        ("license", check_license),
    )
    for name, check in checks:
        try:
            check()
        except CheckFailure as error:
            print(f"HACS_OFFLINE=FAIL reason={error}")
            return 1
        except Exception:
            print(f"HACS_OFFLINE=FAIL reason={name}-unexpected-error")
            return 1
        print(f"HACS_OFFLINE_CHECK={name}:PASS")
    print("HACS_OFFLINE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
