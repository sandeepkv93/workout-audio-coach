from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__: str = version("workout-audio-coach")
except PackageNotFoundError:  # pragma: no cover - fallback for uninstalled source tree
    __version__ = "0.3.0"
