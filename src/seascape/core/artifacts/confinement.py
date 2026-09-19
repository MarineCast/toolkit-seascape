"""Candidate write boundary shared by family artifact writers."""

from __future__ import annotations

import os
from pathlib import Path


def validate_candidate_destination(path: str | Path) -> Path:
    destination = Path(path).expanduser().resolve()
    candidate = os.environ.get("SEASCAPE_CANDIDATE_ROOT")
    if candidate and not destination.is_relative_to(Path(candidate).resolve()):
        raise ValueError(f"Artifact destination escapes candidate root: {destination}")
    return destination
