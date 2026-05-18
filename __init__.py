"""Hermes memory provider entry for directory-based discovery.

When installed to ``~/.hermes/plugins/maindex/``, Hermes loads this module.
Implementation lives in :mod:`maindex_hermes_plugin`.
"""

from maindex_hermes_plugin import MaindexMemoryProvider, register

__all__ = ["MaindexMemoryProvider", "register"]
