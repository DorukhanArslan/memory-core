"""The project's name in every form the runtime spells.

pyproject.toml declares the name: ``[project] name`` is DIST_NAME and ``display-name`` in
``[tool.<package>]`` is DISPLAY_NAME. This module repeats those two values, since an installed
package has no pyproject.toml, and derives the other forms; runtime code spells the name only
through these constants. ``scripts/rename_project.py --to`` rewrites both places, and its
``--check`` (tests/unit/test_project_name.py) fails when they disagree.
"""

# The distribution name (lower-case words joined by "-"), also the slug that starts file and
# directory names.
DIST_NAME = "memory-core"
# How prose and the UI write the product.
DISPLAY_NAME = "memory-core"

# The import package.
PACKAGE_NAME = DIST_NAME.replace("-", "_")
# The upper-case form of runtime markers, and the prefix of every environment name.
UPPER_NAME = PACKAGE_NAME.upper()
ENV_PREFIX = f"{UPPER_NAME}_"
# The workspace state directory (setup state, index, automation store, migration backups).
STATE_DIRNAME = f".{DIST_NAME}"
