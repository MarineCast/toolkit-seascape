"""Checkout entry point; implementation lives in the installed package."""
from seascape.maintenance.validate_seascape_rebuild import *  # noqa: F401,F403

if __name__ == "__main__":
    raise SystemExit(main())
