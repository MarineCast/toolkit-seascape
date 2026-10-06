# Vendored MarineCast study-v1 validation vocabulary, 2026-10-06.
# Shared schema SHA256: 8f138f0de9bf5be0df52739528e083db759537a68a1fe84cf35beac9bc1f9cda.
# Shared validator SHA256: ddbd77f2ff7fa38370fba231814068de602bbdc4824329cf157c3da35bab9620.
# Local adaptation: packaged schema and validation of one captured byte snapshot.
# No runtime import of the workspace validator or sibling repositories.
"""Validate MarineCast study v1 JSON; no runtime or sibling-repo dependencies."""

import argparse
import hashlib
import json
import math
import os
import re
from datetime import date, datetime
from importlib.resources import files
from pathlib import Path


def canonical_bytes(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path):
    return json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=unique_object,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
    )


def check(value, schema, path="$"):
    """Validate the deliberately small schema vocabulary used by study.schema.json."""
    types = schema.get("type", [])
    types = [types] if isinstance(types, str) else types
    matches = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "null": value is None,
        "integer": type(value) is int,
        "number": type(value) in (int, float) and math.isfinite(value),
    }
    if types and not any(matches[t] for t in types):
        raise ValueError(f"{path}: expected {types}")
    if "const" in schema and (
        value != schema["const"] or type(value) != type(schema["const"])
    ):
        raise ValueError(f"{path}: unexpected constant")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path}: invalid enum")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        missing = set(schema.get("required", [])) - value.keys()
        unknown = value.keys() - properties.keys()
        if missing or (unknown and schema.get("additionalProperties") is False):
            raise ValueError(
                f"{path}: missing={sorted(missing)}, unknown={sorted(unknown)}"
            )
        for key in value.keys() & properties.keys():
            check(value[key], properties[key], f"{path}.{key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get(
            "maxItems", math.inf
        ):
            raise ValueError(f"{path}: invalid array length")
        for index, item in enumerate(value):
            check(item, schema.get("items", {}), f"{path}[{index}]")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            raise ValueError(f"{path}: string too short")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            raise ValueError(f"{path}: invalid pattern")
        if schema.get("format") == "date":
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError(f"{path}: expected YYYY-MM-DD")
            date.fromisoformat(value)
        if schema.get("format") == "date-time":
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError(f"{path}: approval timestamp requires timezone")
    if type(value) in (int, float) and value < schema.get("minimum", -math.inf):
        raise ValueError(f"{path}: below minimum")


def geometry_identity(config):
    west, south, east, north = config["domain"]["bbox_wgs84"]
    if not (-180 <= west < east <= 180 and -90 < south < north < 90):
        raise ValueError("invalid non-antimeridian WGS84 rectangle")
    geometry = {
        "type": "Polygon",
        "coordinates": [
            [[west, south], [east, south], [east, north], [west, north], [west, south]]
        ],
    }
    identity = {
        "crs": config["domain"]["crs"],
        "boundary_semantics": config["domain"]["boundary_semantics"],
        "geometry": geometry,
    }
    return hashlib.sha256(canonical_bytes(identity)).hexdigest()


def resolve_config_path(explicit_path=None):
    # Explicit path always wins; there is no guessed default or sibling lookup.
    selected = (
        explicit_path
        if explicit_path is not None
        else os.environ.get("MARINECAST_STUDY_CONFIG")
    )
    if not selected:
        raise ValueError("supply --study-config PATH or MARINECAST_STUDY_CONFIG")
    return Path(selected).expanduser().resolve()


def validate_snapshot(raw, path, require_approved=True):
    """Validate the same captured bytes used for raw and canonical provenance."""
    path = Path(path).resolve()
    config = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=unique_object,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
    )
    check(
        config,
        json.loads(
            files("seascape")
            .joinpath("resources/contracts/study.schema.json")
            .read_text(encoding="utf-8")
        ),
    )
    if date.fromisoformat(config["time"]["start"]) >= date.fromisoformat(
        config["time"]["end_exclusive"]
    ):
        raise ValueError("requested date interval must have start < end_exclusive")
    geometry_hash = geometry_identity(config)
    if config["domain"]["geometry_sha256"] != geometry_hash:
        raise ValueError(
            "geometry_sha256 mismatch: update revision and identity deliberately"
        )
    if config["domain"]["status"] == "approved" and not config["domain"].get(
        "approval"
    ):
        raise ValueError("approved domain requires explicit approval provenance")
    if require_approved and config["domain"]["status"] != "approved":
        raise ValueError(
            "domain remains proposed; production run requires approved geometry"
        )
    registry = config["grid_registry"]
    if registry["status"] == "validated":
        if (
            not registry["mask_revision"]
            or not registry["mask_sha256"]
            or not registry["memberships"]
        ):
            raise ValueError("validated registry requires pinned mask and memberships")
    roles = [(m["resolution"], m["role"]) for m in registry["memberships"]]
    if len(roles) != len(set(roles)):
        raise ValueError("duplicate registry resolution/role")
    root = Path(config["storage"]["data_root"])
    if root.is_absolute():
        raise ValueError("data_root must be portable and relative to the config file")
    return config, {
        "study_id": config["study_id"],
        "domain_status": config["domain"]["status"],
        "domain_revision": config["domain"]["revision"],
        "geometry_sha256": geometry_hash,
        "config_sha256": hashlib.sha256(canonical_bytes(config)).hexdigest(),
        "resolved_data_root": str((path.parent / root).resolve()),
    }


def validate(path=None, require_approved=True):
    path = resolve_config_path(path)
    return validate_snapshot(path.read_bytes(), path, require_approved)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-config", type=Path)
    parser.add_argument(
        "--planning",
        action="store_true",
        help="inspect proposed config without production approval",
    )
    args = parser.parse_args()
    try:
        _, report = validate(args.study_config, not args.planning)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(2, f"invalid study config: {exc}\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
