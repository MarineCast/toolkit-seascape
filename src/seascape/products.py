"""Read current flat Seascape area tables without data release identities."""

from typing import Any

from seascape.domain_parquets import (
    AreaTables,
    list_areas,
    output_root,
    read_area,
    write_areas,
)

__all__ = ["AreaTables", "list_areas", "output_root", "read_area", "write_areas"]


def __getattr__(name: str) -> Any:
    # Keep pre-existing application imports readable while they migrate. These
    # readers never participate in the current output/build workflow.
    if name in {
        "ProductArtifact",
        "list_products",
        "list_resolutions",
        "resolve_product",
    }:
        import warnings

        from seascape import legacy_products

        warnings.warn(
            f"{name} reads historical releases only; use read_area for current Data/Seascape outputs",
            DeprecationWarning,
            stacklevel=2,
        )
        return getattr(legacy_products, name)
    raise AttributeError(name)
