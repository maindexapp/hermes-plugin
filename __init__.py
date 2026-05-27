"""Maindex memory plugin — MemoryProvider interface.

Structured memory graph with semantic + relational recall via the Maindex
Expert REST API. Stores memories with tags, collections, typed associations,
and full revision history. Multi-tier retrieval: exact match, relaxed OR
fallback with synonym expansion, fuzzy trigram, and semantic/hybrid search.

Connects to https://expert.maindex.io — the full Expert API surface.

Config via environment variables (profile-scoped via each profile's .env):
  MAINDEX_API_KEY   — Maindex API key (from https://maindex.io/dashboard)
  MAINDEX_TOKEN     — OAuth bearer token (alternative to API key)
"""

from __future__ import annotations

import getpass
import json
import logging
import os
import stat
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent.memory_provider import MemoryProvider
from tools.registry import tool_error

logger = logging.getLogger(__name__)

_BREAKER_THRESHOLD = 5
_BREAKER_COOLDOWN_SECS = 120

_READ_TIMEOUT = 8
_WRITE_TIMEOUT = 15

_MIN_QUERY_LEN = 10


def _unwrap_envelope(body: Any) -> Any:
    """Unwrap Expert API envelope ``{ ok, data, meta }`` for callers."""
    if isinstance(body, dict) and body.get("ok") is True and "data" in body:
        return body["data"]
    return body


def _as_item_list(body: Any) -> Dict[str, Any]:
    """Normalize list endpoints to ``{ items: [...] }`` for provider code."""
    if isinstance(body, dict) and body.get("ok") is True:
        data = body.get("data")
        if isinstance(data, list):
            result: Dict[str, Any] = {"items": data}
            meta = body.get("meta")
            if isinstance(meta, dict) and "total" in meta:
                result["total"] = meta["total"]
            return result
    if isinstance(body, dict) and "items" in body:
        return body
    if isinstance(body, list):
        return {"items": body}
    return {"items": []}


# ---------------------------------------------------------------------------
# REST client
# ---------------------------------------------------------------------------

class MaindexClient:
    """Thin REST wrapper around the Maindex Expert API."""

    BASE_URL = "https://expert.maindex.io"

    def __init__(self, api_key: str = "", bearer_token: str = ""):
        import httpx

        headers = {"Content-Type": "application/json"}
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        if api_key:
            headers["X-API-Key"] = api_key

        self._client = httpx.Client(
            base_url=self.BASE_URL,
            headers=headers,
            timeout=httpx.Timeout(_READ_TIMEOUT, write=_WRITE_TIMEOUT),
        )

    def search(self, q: str, *, limit: int = 5,
               search_strategy: str = "auto", **filters) -> dict:
        params: Dict[str, Any] = {
            "q": q[:1000], "limit": limit,
            "search_strategy": search_strategy,
        }
        params.update({k: v for k, v in filters.items() if v is not None})
        resp = self._client.get("/v1/search", params=params)
        resp.raise_for_status()
        return _as_item_list(resp.json())

    def keep(self, headline: str, body: str = "", tags: Optional[List[str]] = None,
             kind: str = "note", **kwargs) -> dict:
        payload: Dict[str, Any] = {"headline": headline, "body": body,
                                    "kind": kind}
        if tags:
            payload["tags"] = tags
        payload.update({k: v for k, v in kwargs.items() if v is not None})
        resp = self._client.post("/v1/memories", json=payload)
        resp.raise_for_status()
        data = _unwrap_envelope(resp.json())
        return data if isinstance(data, dict) else {}

    def recall(self, memory_id: str, include_links: bool = True) -> dict:
        params = {"include_links": str(include_links).lower()}
        resp = self._client.get(f"/v1/memories/{memory_id}", params=params)
        resp.raise_for_status()
        data = _unwrap_envelope(resp.json())
        return data if isinstance(data, dict) else {}

    def update(self, memory_id: str, mode: str, **kwargs) -> dict:
        payload: Dict[str, Any] = {"mode": mode}
        payload.update({k: v for k, v in kwargs.items() if v is not None})
        resp = self._client.post(f"/v1/memories/{memory_id}/update",
                                 json=payload)
        resp.raise_for_status()
        data = _unwrap_envelope(resp.json())
        return data if isinstance(data, dict) else {}

    def forget(self, memory_id: str) -> dict:
        resp = self._client.delete(f"/v1/memories/{memory_id}")
        resp.raise_for_status()
        data = _unwrap_envelope(resp.json())
        return data if isinstance(data, dict) else {}

    def list_memories(self, **filters) -> dict:
        params = {k: v for k, v in filters.items() if v is not None}
        resp = self._client.get("/v1/memories", params=params)
        resp.raise_for_status()
        return _as_item_list(resp.json())

    def close(self):
        self._client.close()


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    from hermes_constants import get_hermes_home

    config = {
        "api_key": os.environ.get("MAINDEX_API_KEY", ""),
        "token": os.environ.get("MAINDEX_TOKEN", ""),
        "collection": os.environ.get("MAINDEX_COLLECTION", ""),
        "sync_turns": False,
    }

    config_path = get_hermes_home() / "maindex.json"
    if config_path.exists():
        try:
            file_cfg = json.loads(config_path.read_text(encoding="utf-8"))
            for key, value in file_cfg.items():
                if value is None or value == "":
                    continue
                if key == "sync_turns":
                    config["sync_turns"] = bool(value)
                else:
                    config[key] = value
        except Exception:
            pass

    return config


# ---------------------------------------------------------------------------
# Setup wizard helpers (used by post_setup and CLI)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

SEARCH_SCHEMA = {
    "name": "maindex_search",
    "description": (
        "Search Maindex memories by meaning, keywords, or concepts. "
        "Multi-tier retrieval: full-text, fuzzy, semantic, and hybrid search. "
        "Returns relevance-ranked results with match context."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string",
                       "description": "What to search for."},
            "limit": {"type": "integer",
                       "description": "Max results (default: 10, max: 50)."},
            "tags": {"type": "array", "items": {"type": "string"},
                     "description": "Filter by tags."},
            "kind": {"type": "string",
                     "description": "Filter by memory kind (note, fact, idea, decision, constraint, question, summary, artifact, task_context)."},
            "collection": {"type": "string",
                          "description": "Filter by collection slug or ID."},
        },
        "required": ["query"],
    },
}

KEEP_SCHEMA = {
    "name": "maindex_keep",
    "description": (
        "Store a new memory in Maindex. Memories are structured with a "
        "headline, optional body, tags, and kind. Use for decisions, facts, "
        "constraints, ideas — anything worth remembering across sessions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "headline": {"type": "string",
                         "description": "Title or core assertion (required)."},
            "body": {"type": "string",
                     "description": "Supporting detail. Omit if headline is self-contained."},
            "tags": {"type": "array", "items": {"type": "string"},
                     "description": "Tags for categorization. Use facet:name format (e.g. domain:auth, project:my-app)."},
            "kind": {"type": "string",
                     "description": "Memory type: note, fact, idea, decision, constraint, question, summary, artifact, task_context."},
            "collections": {"type": "array", "items": {"type": "string"},
                           "description": "Collection slugs to add this memory to."},
        },
        "required": ["headline"],
    },
}

RECALL_SCHEMA = {
    "name": "maindex_recall",
    "description": (
        "Retrieve a specific memory by ID (UUID or short ID like mem-1a). "
        "Returns the full memory with tags, collections, metadata, and links."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "memory_id": {"type": "string",
                          "description": "Memory ID (UUID or short ID)."},
        },
        "required": ["memory_id"],
    },
}

UPDATE_SCHEMA = {
    "name": "maindex_update",
    "description": (
        "Update an existing memory by creating a new revision. Full history "
        "is preserved. Tags are additive. Modes: body_append, body_replace, "
        "headline_replace, headline_and_body_replace, revision_only."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "memory_id": {"type": "string",
                          "description": "Memory ID to update."},
            "mode": {"type": "string",
                     "description": "How to apply: body_append, body_replace, headline_replace, headline_and_body_replace, revision_only."},
            "headline": {"type": "string",
                         "description": "New headline text."},
            "body": {"type": "string",
                     "description": "New body text."},
            "tags": {"type": "array", "items": {"type": "string"},
                     "description": "Tags to add (additive)."},
            "kind": {"type": "string",
                     "description": "Change the memory kind (note, fact, idea, decision, constraint, question, summary, artifact, task_context)."},
            "canon_status": {"type": "string",
                             "description": "Set canon status: draft, proposed, accepted, deprecated, alternative, meta."},
            "confidence": {"type": "integer",
                           "description": "Confidence as integer percentage 0-100."},
            "verification_status": {"type": "string",
                                    "description": "Set verification status: unverified, verified, disputed, superseded."},
        },
        "required": ["memory_id", "mode"],
    },
}

FORGET_SCHEMA = {
    "name": "maindex_forget",
    "description": (
        "Soft-delete a memory (restorable). Use when a memory is no longer "
        "relevant or was created in error."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "memory_id": {"type": "string",
                          "description": "Memory ID to delete."},
        },
        "required": ["memory_id"],
    },
}


# ---------------------------------------------------------------------------
# MemoryProvider implementation
# ---------------------------------------------------------------------------

class MaindexMemoryProvider(MemoryProvider):
    """Maindex structured memory via the Expert REST API."""

    def __init__(self):
        self._config: Optional[dict] = None
        self._client: Optional[MaindexClient] = None
        self._session_id = ""
        self._collection = ""
        self._platform = ""
        self._user_id = ""
        self._chat_id = ""
        self._chat_type = ""
        self._sync_turns = False
        self._prefetch_result = ""
        self._prefetch_lock = threading.Lock()
        self._prefetch_thread: Optional[threading.Thread] = None
        self._sync_thread: Optional[threading.Thread] = None
        self._consecutive_failures = 0
        self._breaker_open_until = 0.0

    @property
    def name(self) -> str:
        return "maindex"

    def is_available(self) -> bool:
        cfg = _load_config()
        return bool(cfg.get("api_key") or cfg.get("token"))

    def get_config_schema(self):
        return [
            {
                "key": "api_key",
                "description": "Maindex API key",
                "secret": True,
                "required": False,
                "env_var": "MAINDEX_API_KEY",
                "url": "https://maindex.io/dashboard",
            },
            {
                "key": "token",
                "description": "OAuth bearer token (alternative to API key)",
                "secret": True,
                "required": False,
                "env_var": "MAINDEX_TOKEN",
            },
            {
                "key": "collection",
                "description": "Default collection for scoping memories (optional)",
                "default": "",
            },
            {
                "key": "sync_turns",
                "description": (
                    "Log each conversation turn to Maindex automatically "
                    "(off by default; use maindex_keep for intentional memories)"
                ),
                "default": False,
            },
        ]

    def save_config(self, values: Dict[str, Any], hermes_home: str) -> None:
        config_path = Path(hermes_home) / "maindex.json"
        existing = {}
        if config_path.exists():
            try:
                existing = json.loads(config_path.read_text())
            except Exception:
                pass
        existing.update(values)
        config_path.write_text(json.dumps(existing, indent=2))

    def post_setup(self, hermes_home: str, config: dict) -> None:
        """Run setup wizard after ``hermes memory setup`` selects Maindex."""
        run_setup_wizard(hermes_home, config)

    def _is_breaker_open(self) -> bool:
        if self._consecutive_failures < _BREAKER_THRESHOLD:
            return False
        if time.monotonic() >= self._breaker_open_until:
            self._consecutive_failures = 0
            return False
        return True

    def _record_success(self):
        self._consecutive_failures = 0

    def _record_failure(self):
        self._consecutive_failures += 1
        if self._consecutive_failures >= _BREAKER_THRESHOLD:
            self._breaker_open_until = (time.monotonic()
                                        + _BREAKER_COOLDOWN_SECS)
            logger.warning(
                "Maindex circuit breaker tripped after %d consecutive "
                "failures. Pausing API calls for %ds.",
                self._consecutive_failures, _BREAKER_COOLDOWN_SECS,
            )

    def _source_metadata(self) -> Dict[str, Any]:
        source: Dict[str, Any] = {"origin": "hermes"}
        if self._platform:
            source["platform"] = self._platform
        if self._user_id:
            source["user_id"] = self._user_id
        if self._chat_id:
            source["chat_id"] = self._chat_id
        if self._chat_type:
            source["chat_type"] = self._chat_type
        return source

    def _auto_tags(self, *extra: str) -> List[str]:
        tags = ["source:hermes"]
        if self._platform:
            tags.append(f"platform:{self._platform}")
        tags.extend(extra)
        return tags

    def initialize(self, session_id: str, **kwargs) -> None:
        self._config = _load_config()
        self._session_id = session_id
        self._collection = self._config.get("collection", "")
        self._sync_turns = bool(self._config.get("sync_turns", False))
        self._platform = str(kwargs.get("platform") or "").strip()
        self._user_id = str(kwargs.get("user_id") or "").strip()
        self._chat_id = str(kwargs.get("chat_id") or "").strip()
        self._chat_type = str(kwargs.get("chat_type") or "").strip()
        self._client = MaindexClient(
            api_key=self._config.get("api_key", ""),
            bearer_token=self._config.get("token", ""),
        )

    def system_prompt_block(self) -> str:
        parts = ["# Maindex Memory", "Active. Structured knowledge graph."]
        if self._collection:
            parts.append(f"Default collection: {self._collection}.")
        parts.append(
            "Use maindex_search to find memories, maindex_keep to store facts, "
            "maindex_recall for a specific memory, maindex_update to revise, "
            "maindex_forget to delete."
        )
        return "\n".join(parts)

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        if self._prefetch_thread and self._prefetch_thread.is_alive():
            self._prefetch_thread.join(timeout=3.0)
        with self._prefetch_lock:
            result = self._prefetch_result
            self._prefetch_result = ""
        if not result:
            return ""
        return f"## Maindex Memory\n{result}"

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        if self._is_breaker_open() or not self._client:
            return
        if not query or len(query.strip()) < _MIN_QUERY_LEN:
            return

        def _run():
            try:
                filters: Dict[str, Any] = {}
                if self._collection:
                    filters["collection"] = self._collection
                data = self._client.search(
                    query.strip()[:1000], limit=5,
                    search_strategy="auto", **filters,
                )
                items = data.get("items", [])
                if items:
                    lines = []
                    for m in items:
                        headline = m.get("headline", "")
                        short_id = m.get("shortId", "")
                        body = m.get("body", "")
                        entry = f"- [{short_id}] {headline}"
                        if body:
                            entry += f": {body[:200]}"
                        lines.append(entry)
                    with self._prefetch_lock:
                        self._prefetch_result = "\n".join(lines)
                self._record_success()
            except Exception as e:
                self._record_failure()
                logger.debug("Maindex prefetch failed: %s", e)

        self._prefetch_thread = threading.Thread(
            target=_run, daemon=True, name="maindex-prefetch",
        )
        self._prefetch_thread.start()

    def sync_turn(self, user_content: str, assistant_content: str,
                  *, session_id: str = "") -> None:
        if not self._sync_turns:
            return
        if self._is_breaker_open() or not self._client:
            return
        if len(user_content.strip()) < _MIN_QUERY_LEN:
            return

        def _sync():
            try:
                headline = user_content[:200].strip()
                if len(user_content) > 200:
                    headline += "..."
                body = (f"User: {user_content[:2000]}\n"
                        f"Assistant: {assistant_content[:2000]}")
                keep_kw: Dict[str, Any] = {
                    "source": self._source_metadata(),
                    "conversations": [{
                        "conversation_type": "hermes_session",
                        "conversation_key": self._session_id,
                    }],
                }
                if self._collection:
                    keep_kw["collections"] = [self._collection]
                self._client.keep(
                    headline=headline, body=body,
                    tags=self._auto_tags(), kind="note", **keep_kw,
                )
                self._record_success()
            except Exception as e:
                self._record_failure()
                logger.warning("Maindex sync failed: %s", e)

        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=5.0)

        self._sync_thread = threading.Thread(
            target=_sync, daemon=True, name="maindex-sync",
        )
        self._sync_thread.start()

    def on_memory_write(self, action: str, target: str, content: str,
                        metadata: Optional[Dict[str, Any]] = None) -> None:
        if action not in ("add", "replace") or not content or not self._client:
            return
        if self._is_breaker_open():
            return

        def _write():
            try:
                label = "User profile" if target == "user" else "Agent memory"
                keep_kw: Dict[str, Any] = {
                    "source": self._source_metadata(),
                }
                if self._collection:
                    keep_kw["collections"] = [self._collection]
                self._client.keep(
                    headline=f"[{label}] {content[:200]}",
                    body=content if len(content) > 200 else "",
                    tags=self._auto_tags(f"hermes:{target}"),
                    kind="fact", **keep_kw,
                )
                self._record_success()
            except Exception as e:
                self._record_failure()
                logger.debug("Maindex memory mirror failed: %s", e)

        t = threading.Thread(target=_write, daemon=True, name="maindex-memwrite")
        t.start()

    def on_pre_compress(self, messages: List[Dict[str, Any]]) -> str:
        if not messages or not self._client:
            return ""

        parts = []
        for msg in messages[-10:]:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip() and role in ("user", "assistant"):
                parts.append(f"{role}: {content[:500]}")

        if not parts:
            return ""

        combined = "\n".join(parts)

        def _flush():
            try:
                keep_kw: Dict[str, Any] = {
                    "source": self._source_metadata(),
                    "conversations": [{
                        "conversation_type": "hermes_session",
                        "conversation_key": self._session_id,
                    }],
                }
                if self._collection:
                    keep_kw["collections"] = [self._collection]
                self._client.keep(
                    headline="Pre-compression context snapshot",
                    body=combined,
                    tags=self._auto_tags("hermes:compression"),
                    kind="summary", **keep_kw,
                )
                self._record_success()
                logger.info("Maindex pre-compression flush: %d messages",
                            len(parts))
            except Exception as e:
                self._record_failure()
                logger.debug("Maindex pre-compression flush failed: %s", e)

        t = threading.Thread(target=_flush, daemon=True, name="maindex-flush")
        t.start()
        return ""

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return [SEARCH_SCHEMA, KEEP_SCHEMA, RECALL_SCHEMA, UPDATE_SCHEMA,
                FORGET_SCHEMA]

    def handle_tool_call(self, tool_name: str, args: dict, **kwargs) -> str:
        if self._is_breaker_open():
            return json.dumps({
                "error": "Maindex API temporarily unavailable "
                         "(multiple consecutive failures). Will retry "
                         "automatically."
            })

        if not self._client:
            return tool_error("Maindex client not initialized")

        if tool_name == "maindex_search":
            return self._tool_search(args)
        elif tool_name == "maindex_keep":
            return self._tool_keep(args)
        elif tool_name == "maindex_recall":
            return self._tool_recall(args)
        elif tool_name == "maindex_update":
            return self._tool_update(args)
        elif tool_name == "maindex_forget":
            return self._tool_forget(args)
        return tool_error(f"Unknown tool: {tool_name}")

    def shutdown(self) -> None:
        for t in (self._prefetch_thread, self._sync_thread):
            if t and t.is_alive():
                t.join(timeout=5.0)
        if self._client:
            self._client.close()
            self._client = None

    # -- Tool implementations ------------------------------------------------

    def _tool_search(self, args: dict) -> str:
        query = args.get("query", "")
        if not query:
            return tool_error("query is required")
        try:
            filters: Dict[str, Any] = {}
            for key in ("tags", "kind", "collection"):
                if args.get(key):
                    filters[key] = args[key]
            if self._collection and "collection" not in filters:
                filters["collection"] = self._collection
            data = self._client.search(
                query, limit=min(int(args.get("limit", 10)), 50),
                **filters,
            )
            self._record_success()
            items = data.get("items", [])
            if not items:
                return json.dumps({"result": "No relevant memories found."})
            results = []
            for m in items:
                entry: Dict[str, Any] = {
                    "id": m.get("shortId", m.get("id", "")),
                    "headline": m.get("headline", ""),
                    "score": m.get("score"),
                }
                if m.get("body"):
                    entry["body"] = m["body"][:500]
                if m.get("tags"):
                    entry["tags"] = m["tags"]
                results.append(entry)
            return json.dumps({"results": results, "count": len(results)})
        except Exception as e:
            self._record_failure()
            return tool_error(f"Search failed: {e}")

    def _tool_keep(self, args: dict) -> str:
        headline = args.get("headline", "")
        if not headline:
            return tool_error("headline is required")
        try:
            keep_kwargs: Dict[str, Any] = {}
            if args.get("body"):
                keep_kwargs["body"] = args["body"]
            if args.get("tags"):
                keep_kwargs["tags"] = args["tags"]
            if args.get("kind"):
                keep_kwargs["kind"] = args["kind"]
            if args.get("collections"):
                keep_kwargs["collections"] = args["collections"]
            elif self._collection:
                keep_kwargs["collections"] = [self._collection]
            keep_kwargs["conversations"] = [{
                "conversation_type": "hermes_session",
                "conversation_key": self._session_id,
            }]
            keep_kwargs["source"] = self._source_metadata()
            data = self._client.keep(headline, **keep_kwargs)
            self._record_success()
            return json.dumps({
                "result": "Memory stored.",
                "id": data.get("shortId", data.get("id", "")),
                "headline": data.get("headline", ""),
            })
        except Exception as e:
            self._record_failure()
            return tool_error(f"Failed to store: {e}")

    def _tool_recall(self, args: dict) -> str:
        memory_id = args.get("memory_id", "")
        if not memory_id:
            return tool_error("memory_id is required")
        try:
            data = self._client.recall(memory_id)
            self._record_success()
            result: Dict[str, Any] = {
                "id": data.get("shortId", data.get("id", "")),
                "headline": data.get("headline", ""),
                "body": data.get("body", ""),
                "tags": data.get("tags", []),
                "kind": data.get("kind", ""),
                "canon_status": data.get("canonStatus", ""),
                "collections": data.get("collections", []),
                "created": data.get("createdAt", ""),
                "updated": data.get("updatedAt", ""),
            }
            return json.dumps(result)
        except Exception as e:
            self._record_failure()
            return tool_error(f"Recall failed: {e}")

    def _tool_update(self, args: dict) -> str:
        memory_id = args.get("memory_id", "")
        mode = args.get("mode", "")
        if not memory_id:
            return tool_error("memory_id is required")
        if not mode:
            return tool_error("mode is required")
        try:
            update_kwargs: Dict[str, Any] = {}
            for key in ("headline", "body", "tags", "kind", "canon_status",
                         "confidence", "verification_status"):
                if args.get(key) is not None:
                    update_kwargs[key] = args[key]
            data = self._client.update(memory_id, mode, **update_kwargs)
            self._record_success()
            return json.dumps({
                "result": "Memory updated.",
                "id": data.get("shortId", data.get("id", "")),
            })
        except Exception as e:
            self._record_failure()
            return tool_error(f"Update failed: {e}")

    def _tool_forget(self, args: dict) -> str:
        memory_id = args.get("memory_id", "")
        if not memory_id:
            return tool_error("memory_id is required")
        try:
            self._client.forget(memory_id)
            self._record_success()
            return json.dumps({"result": "Memory deleted."})
        except Exception as e:
            self._record_failure()
            return tool_error(f"Delete failed: {e}")


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    """Register Maindex as a memory provider plugin."""
    ctx.register_memory_provider(MaindexMemoryProvider())
