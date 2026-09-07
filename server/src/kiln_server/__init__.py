# SPDX-License-Identifier: Apache-2.0
# Copyright (C) Kiln Contributors -- see LICENSE-SERVER
"""Kiln server package."""
from .main import app, manager, VERSION

__all__ = ["app", "manager", "VERSION"]
__version__ = VERSION
