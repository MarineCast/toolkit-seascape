"""Read workspace-local dotenv values without changing the process environment."""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

from .paths import project_root

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def environment_values() -> dict[str, str]:
    """Process values override one explicit or workspace-local .env file.

    No parent search, shell execution, interpolation, or global environment mutation.
    Parse failures identify the line, never its potentially secret contents.
    """
    explicit = os.environ.get("SEASCAPE_ENV_FILE")
    path = (project_root() / Path(explicit or ".env").expanduser()).resolve()
    values: dict[str, str] = {}
    if explicit or path.exists():
        for number, line in enumerate(
            path.read_text(encoding="utf-8-sig").splitlines(), 1
        ):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            name, separator, raw = line.partition("=")
            name = name.strip()
            try:
                if not separator or not _NAME.fullmatch(name) or name in values:
                    raise ValueError
                tokens = shlex.split(raw, comments=True, posix=True)
                if len(tokens) > 1:
                    raise ValueError
            except ValueError:
                raise ValueError(f"Invalid .env assignment at line {number}") from None
            values[name] = tokens[0] if tokens else ""
    return {**values, **os.environ}


def required_environment_value(name: str) -> str:
    """Resolve a runtime-only credential without putting it into configuration."""
    if not _NAME.fullmatch(name):
        raise ValueError("Invalid credential environment-variable name")
    value = environment_values().get(name)
    if not value:
        raise ValueError(f"Required environment variable is not set: {name}")
    if "\r" in value or "\n" in value:
        raise ValueError(f"Environment variable contains an invalid newline: {name}")
    return value
