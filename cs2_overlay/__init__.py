"""CS2 Toolkit automation package.

Modules: config (tunables) · core (window/screen/input primitives) ·
flows (automation behaviors + state machine) · runtime (launch wiring).
Entry point: overlay.py at the project root.
"""

from .config import VERSION

__all__ = ["VERSION"]
