"""Seascape environmental features and publication contracts."""

from importlib.metadata import version

from .products import ProductArtifact, list_products, list_resolutions, resolve_product
from .publication import SeascapeReleasePublisher, SeascapeSnapshot

__version__ = version("toolkit-seascape")

__all__ = [
    "ProductArtifact",
    "SeascapeReleasePublisher",
    "SeascapeSnapshot",
    "__version__",
    "list_products",
    "list_resolutions",
    "resolve_product",
]
