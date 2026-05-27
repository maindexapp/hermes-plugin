"""Maindex setup wizard shared by ``post_setup`` and ``hermes maindex`` CLI."""

from __future__ import annotations

import getpass
import os
import stat
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

from maindex_hermes_plugin import MaindexClient, _load_config


def mask_secret(value: str) -> str:
    """Return a safe display form for secrets."""
    if not value:
        return "not set"
    if len(value) <= 8:
        return "set"
    return f"...{value[-8:]}"


def _prompt(label: str, default: str | None = None, secret: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    if secret:
        sys.stdout.write(f"  {label}{suffix}: ")
        sys.stdout.flush()
        if sys.stdin.isatty():
            val = getpass.getpass(prompt="")
        else:
            val = sys.stdin.readline().strip()
    else:
        sys.stdout.write(f"  {label}{suffix}: ")
        sys.stdout.flush()
        val = sys.stdin.readline().strip()
    return val or (default or "")


def write_env_vars(env_path: Path, env_writes: Dict[str, str]) -> None:
    """Append or update env vars in a profile ``.env`` file."""
    env_path.parent.mkdir(parents=True, exist_ok=True)

    existing_lines: list[str] = []
    if env_path.exists():
        existing_lines = env_path.read_text(encoding="utf-8").splitlines()

    updated_keys: set[str] = set()
    new_lines: list[str] = []
    for line in existing_lines:
        key_match = line.split("=", 1)[0].strip() if "=" in line else ""
        if key_match in env_writes:
            new_lines.append(f"{key_match}={env_writes[key_match]}")
            updated_keys.add(key_match)
        else:
            new_lines.append(line)

    for key, val in env_writes.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={val}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    try:
        env_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def activate_memory_provider() -> None:
    """Persist ``memory.provider: maindex`` to config.yaml."""
    from hermes_cli.config import load_config, save_config

    config = load_config()
    if not isinstance(config.get("memory"), dict):
        config["memory"] = {}
    config["memory"]["provider"] = "maindex"
    save_config(config)


def test_connection(api_key: str = "", bearer_token: str = "") -> Tuple[bool, str]:
    """Verify credentials against the Expert REST API."""
    if not api_key and not bearer_token:
        return False, "No credentials configured"

    client = MaindexClient(api_key=api_key, bearer_token=bearer_token)
    try:
        client.list_memories(limit=1)
        return True, "Connected successfully"
    except Exception as exc:
        return False, str(exc)
    finally:
        client.close()


def run_setup_wizard(hermes_home: str, config: Optional[dict] = None) -> bool:
    """Interactive setup: credentials, activation, and connection test.

    Returns True when Maindex is activated with working credentials.
    """
    home = Path(hermes_home)
    env_path = home / ".env"
    cfg = _load_config()

    print("\nMaindex memory setup\n" + "─" * 40)
    print("  Connect Hermes to the Maindex Expert knowledge graph.")
    print("  API keys: https://maindex.io/dashboard")
    print(f"  Profile:  {home}")
    print()

    api_key = cfg.get("api_key", "")
    token = cfg.get("token", "")
    env_writes: Dict[str, str] = {}

    if api_key:
        new_key = _prompt(
            f"Maindex API key (current: {mask_secret(api_key)}, blank to keep)",
            secret=True,
        )
        if new_key:
            api_key = new_key
            env_writes["MAINDEX_API_KEY"] = new_key
            os.environ["MAINDEX_API_KEY"] = new_key
    elif token:
        print(f"  OAuth token configured ({mask_secret(token)}).")
        use_key = _prompt("Add an API key too? [y/N]", default="n")
        if use_key.lower() in {"y", "yes"}:
            new_key = _prompt("Maindex API key", secret=True)
            if new_key:
                api_key = new_key
                env_writes["MAINDEX_API_KEY"] = new_key
                os.environ["MAINDEX_API_KEY"] = new_key
    else:
        print("  Get an API key at https://maindex.io/dashboard")
        new_key = _prompt("Maindex API key", secret=True)
        if new_key:
            api_key = new_key
            env_writes["MAINDEX_API_KEY"] = new_key
            os.environ["MAINDEX_API_KEY"] = new_key
        else:
            new_token = _prompt(
                "OAuth bearer token (alternative to API key, blank to skip)",
                secret=True,
            )
            if new_token:
                token = new_token
                env_writes["MAINDEX_TOKEN"] = new_token
                os.environ["MAINDEX_TOKEN"] = new_token

    if not api_key and not token:
        print("\n  No credentials configured.")
        print("  Set MAINDEX_API_KEY or MAINDEX_TOKEN in your profile .env,")
        print("  then run: hermes maindex setup\n")
        return False

    current_collection = cfg.get("collection", "")
    collection = _prompt(
        "Default collection slug (optional)",
        default=current_collection or None,
    )

    provider_values: Dict[str, str | bool] = {}
    if collection:
        provider_values["collection"] = collection
        os.environ["MAINDEX_COLLECTION"] = collection

    if env_writes:
        write_env_vars(env_path, env_writes)
        print(f"  Credentials saved to {env_path}")

    if provider_values:
        from maindex_hermes_plugin import MaindexMemoryProvider

        MaindexMemoryProvider().save_config(provider_values, str(home))
        print(f"  Provider config saved to {home / 'maindex.json'}")

    try:
        activate_memory_provider()
        print("  Memory provider set to 'maindex' in config.yaml")
    except Exception as exc:
        print(f"  Could not update config.yaml: {exc}")
        print("  Run: hermes config set memory.provider maindex")
        return False

    print("  Testing connection... ", end="", flush=True)
    ok, message = test_connection(api_key=api_key, bearer_token=token)
    if ok:
        print("OK")
        print("\n  Maindex is ready.")
        print("  Verify anytime: hermes maindex status")
        print("  Start a new Hermes session to use maindex_search / maindex_keep tools.")
        print()
        print("  MCP note: if you also use Maindex via MCP, set the header to")
        print("    X-API-Key — not Authorization: Bearer.")
        print()
        return True

    print("FAILED")
    print(f"  Error: {message}")
    print("  Check your API key and try: hermes maindex test\n")
    return False
