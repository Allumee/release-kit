"""Allumee release kit: build, check and publish a project's release zip.

Standard library only, so the same code runs in GitHub Actions, on a laptop
and from the Claude plugin without installing anything.
"""

KIT_VERSION = "1.0.0"


class KitError(Exception):
    """A problem the person running the command can fix; printed without a traceback."""
