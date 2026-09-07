"""Kiln server package."""
from .main import app, manager, VERSION

__all__ = ["app", "manager", "VERSION"]
__version__ = VERSION
