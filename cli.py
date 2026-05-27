"""CLI commands for Maindex memory provider management.

Handles: hermes maindex setup | status | test

Note: This module is loaded separately by Hermes during argparse setup.
We use late imports to access the main plugin module since it may not
be in sys.modules yet when this file is first imported.
"""

from __future__ import annotations

import sys


def _get_main_module():
    """Get the main plugin module (handles bundled, user-installed, and pip)."""
    for mod_name in (
        "_hermes_user_memory.maindex",  # Hermes user-installed
        "plugins.memory.maindex",        # Hermes bundled
        "maindex_hermes_plugin",         # pip install
        "maindex_plugin",                # test harness
    ):
        if mod_name in sys.modules:
            return sys.modules[mod_name]
    raise ImportError("Maindex plugin not loaded. Run: hermes memory setup")


def cmd_setup(args) -> None:
    """Run the Maindex setup wizard."""
    from hermes_constants import get_hermes_home

    mod = _get_main_module()
    mod.run_setup_wizard(str(get_hermes_home()))


def cmd_status(args) -> None:
    """Show Maindex config and connection status."""
    from hermes_constants import get_hermes_home

    mod = _get_main_module()
    home = get_hermes_home()
    cfg = mod._load_config()
    api_key = cfg.get("api_key", "")
    token = cfg.get("token", "")

    active_provider = ""
    try:
        from hermes_cli.config import load_config

        mem = load_config().get("memory", {})
        if isinstance(mem, dict):
            active_provider = mem.get("provider", "") or ""
    except Exception:
        pass

    print("\nMaindex status\n" + "─" * 40)
    print(f"  Profile:         {home}")
    print(f"  Memory provider: {active_provider or '(not active)'}")
    print(f"  API key:         {mod.mask_secret(api_key)}")
    print(f"  OAuth token:     {mod.mask_secret(token)}")
    if cfg.get("collection"):
        print(f"  Collection:      {cfg['collection']}")
    print(f"  Sync turns:      {bool(cfg.get('sync_turns', False))}")

    config_path = home / "maindex.json"
    if config_path.exists():
        print(f"  Config file:     {config_path}")

    provider = mod.MaindexMemoryProvider()
    if not provider.is_available():
        print("\n  Status:          not available (missing credentials)")
        print("  Run: hermes maindex setup\n")
        return

    if active_provider != "maindex":
        print("\n  Status:          credentials present, provider not active")
        print("  Run: hermes config set memory.provider maindex\n")
        return

    print("\n  Connection... ", end="", flush=True)
    ok, message = mod.test_connection(api_key=api_key, bearer_token=token)
    if ok:
        print("OK")
        print("\n  Tools available in chat: maindex_search, maindex_keep,")
        print("  maindex_recall, maindex_update, maindex_forget\n")
    else:
        print("FAILED")
        print(f"  Error: {message}\n")


def cmd_test(args) -> None:
    """Test Maindex API credentials."""
    mod = _get_main_module()
    cfg = mod._load_config()
    api_key = cfg.get("api_key", "")
    token = cfg.get("token", "")

    if not api_key and not token:
        print("\n  No credentials found.")
        print("  Run: hermes maindex setup\n")
        return

    auth_label = "X-API-Key" if api_key else "Authorization: Bearer (OAuth)"
    print("\n  Testing Maindex Expert API...")
    print("  Endpoint: https://expert.maindex.io/v1/memories")
    print(f"  Auth:     {auth_label} {mod.mask_secret(api_key or token)}")

    ok, message = mod.test_connection(api_key=api_key, bearer_token=token)
    if ok:
        print("  Result:   OK\n")
    else:
        print(f"  Result:   FAILED — {message}\n")
        sys.exit(1)


def maindex_command(args) -> None:
    """Route maindex subcommands."""
    sub = getattr(args, "maindex_command", None)
    if sub == "setup":
        cmd_setup(args)
    elif sub == "test":
        cmd_test(args)
    elif sub in (None, "status"):
        cmd_status(args)
    else:
        print(f"  Unknown maindex command: {sub}")
        print("  Available: setup, status, test\n")


def register_cli(subparser) -> None:
    """Build the ``hermes maindex`` argparse subcommand tree."""
    subs = subparser.add_subparsers(dest="maindex_command")

    subs.add_parser(
        "setup",
        help="Configure credentials, activate provider, and test connection",
    )
    subs.add_parser(
        "status",
        help="Show config and connection status",
    )
    subs.add_parser(
        "test",
        help="Test API credentials against the Expert REST API",
    )
