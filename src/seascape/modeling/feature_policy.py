"""Compatibility imports for the retired model-policy module.

Applications own predictive feature and scale selection. New consumers should
import species-neutral metadata helpers from :mod:`seascape.governance`.
"""

from seascape.governance.feature_eligibility import (
    apply_feature_eligibility,
    audit_collinearity,
    build_feature_eligibility,
    infer_scale_group,
    infer_topology,
    main,
    seascape_catalog_subset,
)

# These aliases preserve source compatibility for static eligibility users only.
apply_feature_policy = apply_feature_eligibility
build_feature_policy = build_feature_eligibility

__all__ = [
    "apply_feature_eligibility",
    "apply_feature_policy",
    "audit_collinearity",
    "build_feature_eligibility",
    "build_feature_policy",
    "infer_scale_group",
    "infer_topology",
    "seascape_catalog_subset",
]


if __name__ == "__main__":
    raise SystemExit(main())
