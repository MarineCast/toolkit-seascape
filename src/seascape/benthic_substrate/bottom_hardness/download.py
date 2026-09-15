"""Validate the dbSEABED substrate inputs used by the hardness layer."""

from __future__ import annotations

from seascape.benthic_substrate.classification.download import (
    DEFAULT_CONFIG_PATH,
    download_substrate_sources,
    main,
)

__all__ = ["DEFAULT_CONFIG_PATH", "download_substrate_sources", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
