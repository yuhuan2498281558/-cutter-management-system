"""Isolated test settings for CI; never use for application serving/migration.

The repository currently omits shield's historical migrations. Tests build
shield fixtures from its current models, while system and AI memory still run
their checked-in migrations. This does not validate shield deployment history.
"""

from copy import deepcopy

from .settings import *  # noqa: F403


MIGRATION_MODULES = {"shield": None}
DATABASES = deepcopy(DATABASES)  # noqa: F405
# Keep clean-checkout verification separate from the regular local test DB.
DATABASES["default"].setdefault("TEST", {})["NAME"] = "test_ai_ci"
