"""CLI commands for Maindex memory provider management.

Handles: hermes maindex setup | status | test
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from hermes_constants import get_hermes_home

from maindex_hermes_plugin import MaindexMemoryProvider, _load_config
from maindex_hermes_plugin.setup import (
    activate_memory_provider,
    mask_secret,
    run_setup_wizard,
    test_connection,
)


def cmd_setup(args) -> None:
    """Run the Maindex setup wizard."""
    run_setup_wizard(str(get_hermes_home()))


def cmd_status(args) -> None:
    """Show Maindex config and connection status."""
    home = get_hermes_home()
    cfg = _load_config()
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
    print(f"  API key:         {mask_secret(api_key)}")
    print(f"  OAuth token:     {mask_secret(token)}")
    if cfg.get("collection"):
        print(f"  Collection:      {cfg['collection']}")
    print(f"  Sync turns:      {bool(cfg.get('sync_turns', False))}")

    config_path = home / "maindex.json"
    if config_path.exists():
        print(f"  Config file:     {config_path}")

    provider = MaindexMemoryProvider()
    if not provider.is_available():
        print("\n  Status:          not available (missing credentials)")
        print("  Run: hermes maindex setup\n")
        return

    if active_provider != "maindex":
        print("\n  Status:          credentials present, provider not active")
        print("  Run: hermes config set memory.provider maindex\n")
        return

    print("\n  Connection... ", end="", flush=True)
    ok, message = test_connection(api_key=api_key, bearer_token=token)
    if ok:
        print("OK")
        print("\n  Tools available in chat: maindex_search, maindex_keep,")
        print("  maindex_recall, maindex_update, maindex_forget\n")
    else:
        print("FAILED")
        print(f"  Error: {message}\n")


def cmd_test(args) -> None:
    """Test Maindex API credentials."""
    cfg = _load_config()
    api_key = cfg.get("api_key", "")
    token = cfg.get("token", "")

    if not api_key and not token:
        print("\n  No credentials found.")
        print("  Run: hermes maindex setup\n")
        return

    auth_label = "X-API-Key" if api_key else "Authorization: Bearer (OAuth)"
    print("\n  Testing Maindex Expert API...")
    print(f"  Endpoint: https://expert.maindex.io/v1/memories")
    print(f"  Auth:     {auth_label} {mask_secret(api_key or token)}")

    ok, message = test_connection(api_key=api_key, bearer_token=token)
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
