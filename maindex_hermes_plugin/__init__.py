"""Maindex Hermes plugin — pip-compatible re-export.

When installed via pip, this package re-exports from the root module.
When loaded by Hermes as a directory, Hermes uses the root __init__.py directly.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# Load the root __init__.py as a module if not already loaded
_root_init = Path(__file__).parent.parent / "__init__.py"
_mod_name = "_maindex_hermes_root"

if _mod_name not in sys.modules and _root_init.exists():
    spec = importlib.util.spec_from_file_location(_mod_name, str(_root_init))
    if spec and spec.loader:
        mod = importlib.util.module_from_spec(spec)
        sys.modules[_mod_name] = mod
        spec.loader.exec_module(mod)

if _mod_name in sys.modules:
    _root = sys.modules[_mod_name]
    
    # Re-export everything
    MaindexClient = _root.MaindexClient
    MaindexMemoryProvider = _root.MaindexMemoryProvider
    register = _root.register
    _load_config = _root._load_config
    mask_secret = _root.mask_secret
    test_connection = _root.test_connection
    run_setup_wizard = _root.run_setup_wizard
    activate_memory_provider = _root.activate_memory_provider
    write_env_vars = _root.write_env_vars
    
    __all__ = [
        "MaindexClient",
        "MaindexMemoryProvider",
        "register",
        "_load_config",
        "mask_secret",
        "test_connection",
        "run_setup_wizard",
        "activate_memory_provider",
        "write_env_vars",
    ]
