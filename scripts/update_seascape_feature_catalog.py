"""Checkout entry point; implementation lives in the installed package."""
from seascape.maintenance.update_seascape_feature_catalog import *  # noqa: F401,F403

if __name__ == "__main__":
    raise SystemExit(main())
