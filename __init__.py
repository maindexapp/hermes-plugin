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


def _bool_query_param(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value).lower()
    return str(value).lower()


def _optional_api_args(args: dict, keys: Tuple[str, ...]) -> Dict[str, Any]:
    """Forward only present, non-None tool args to API calls."""
    return {k: args[k] for k in keys if args.get(k) is not None}


def _collection_from_args(
    args: dict, default_collection: str,
) -> Dict[str, Any]:
    """Resolve collection filter: '*' = none, explicit = use, else default."""
    coll_arg = args.get("collection", "")
    if coll_arg == "*":
        return {}
    if coll_arg:
        return {"collection": coll_arg}
    if default_collection:
        return {"collection": default_collection}
    return {}


def _format_memory_items(
    items: List[dict], *, include_extras: bool = False,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for m in items:
        entry: Dict[str, Any] = {
            "id": m.get("shortId", m.get("id", "")),
            "headline": m.get("headline", ""),
        }
        if m.get("score") is not None:
            entry["score"] = m.get("score")
        if m.get("body"):
            entry["body"] = m["body"][:500]
        if m.get("tags"):
            entry["tags"] = m["tags"]
        if m.get("kind"):
            entry["kind"] = m.get("kind")
        if include_extras:
            if m.get("matchContext"):
                entry["match_context"] = m["matchContext"]
            if m.get("scoreBreakdown"):
                entry["score_breakdown"] = m["scoreBreakdown"]
            if m.get("relationType"):
                entry["relation_type"] = m["relationType"]
        results.append(entry)
    return results


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

    def recall(
        self, memory_id: str, *, include_links: bool = True,
        include_deleted: bool = False, include_revisions: bool = False,
    ) -> dict:
        params = {
            "include_links": _bool_query_param(include_links),
            "include_deleted": _bool_query_param(include_deleted),
            "include_revisions": _bool_query_param(include_revisions),
        }
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

    def restore(self, memory_id: str) -> dict:
        resp = self._client.post(f"/v1/memories/{memory_id}/restore")
        resp.raise_for_status()
        data = _unwrap_envelope(resp.json())
        return data if isinstance(data, dict) else {}

    def create_associations(self, memory_id: str, targets: list) -> dict:
        resp = self._client.post(
            f"/v1/memories/{memory_id}/associations",
            json={"targets": targets},
        )
        resp.raise_for_status()
        data = _unwrap_envelope(resp.json())
        return data if isinstance(data, dict) else {"items": data}

    def discover_associations(self, **filters) -> dict:
        params = {k: v for k, v in filters.items() if v is not None}
        resp = self._client.get("/v1/associations", params=params)
        resp.raise_for_status()
        data = _unwrap_envelope(resp.json())
        return data if isinstance(data, dict) else {}

    def list_collections(
        self, parent_id: str = "", limit: int = 20, offset: int = 0,
    ) -> dict:
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if parent_id:
            params["parent_id"] = parent_id
        resp = self._client.get("/v1/collections", params=params)
        resp.raise_for_status()
        return _as_item_list(resp.json())

    def create_collection(self, name: str, **kwargs) -> dict:
        payload: Dict[str, Any] = {"name": name}
        for key in (
            "slug", "description", "summary_headline", "icon", "color",
            "parent_id", "metadata",
        ):
            val = kwargs.get(key)
            if val:
                payload[key] = val
        resp = self._client.post("/v1/collections", json=payload)
        resp.raise_for_status()
        data = _unwrap_envelope(resp.json())
        return data if isinstance(data, dict) else {}

    def add_collection_members(
        self, collection_id: str, memory_ids: list,
    ) -> dict:
        resp = self._client.post(
            f"/v1/collections/{collection_id}/members",
            json={"memory_ids": memory_ids},
        )
        resp.raise_for_status()
        data = _unwrap_envelope(resp.json())
        return data if isinstance(data, dict) else {}

    def remove_collection_members(
        self, collection_id: str, memory_ids: list,
    ) -> dict:
        resp = self._client.request(
            "DELETE",
            f"/v1/collections/{collection_id}/members",
            json={"memory_ids": memory_ids},
        )
        resp.raise_for_status()
        data = _unwrap_envelope(resp.json())
        return data if isinstance(data, dict) else {}

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
    if current_collection:
        collection_label = f"Default collection (current: {current_collection}, blank to clear)"
    else:
        collection_label = "Default collection slug (optional, blank to skip)"
    collection = _prompt(collection_label)

    provider_values: Dict[str, str | bool] = {}
    if collection or current_collection:
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
        print("  Start a new Hermes session to use maindex_* tools.")
        print()
        _print_install_recommendations(home)
        print()
        print("  MCP note: if you also use Maindex via MCP, set the header to")
        print("    X-API-Key — not Authorization: Bearer.")
        print()
        return True

    print("FAILED")
    print(f"  Error: {message}")
    print("  Check your API key and try: hermes maindex test\n")
    return False


def _plugin_docs_dir() -> Path:
    return Path(__file__).resolve().parent / "docs"


def _print_install_recommendations(hermes_home: Path) -> None:
    """Post-install checklist for the agent to relay to its operator."""
    docs = _plugin_docs_dir()
    print("  Recommended for your user/operator:")
    print("  1. In config.yaml (~/.hermes/config.yaml or /opt/data/config.yaml):")
    print("       memory.provider: maindex")
    print("       memory_enabled: false")
    print("  2. Add the bootstrap persona from:")
    print(f"       {docs / 'PERSONA_BOOTSTRAP.md'}")
    print("  3. Replace mem-YOUR_ID with their identity memory short ID.")
    print(f"  4. Optional deep guide: {docs / 'AGENT_MEMORY.md'}")
    print()
    print("  Tell your user:")
    print("  On session start, load your identity record from Maindex via")
    print("  maindex_recall(memory_id='mem-YOUR_ID'). Keep a local copy with a")
    print("  timestamp in case of service interruption.")


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

_KIND_DESC = (
    "note, fact, idea, decision, constraint, question, summary, artifact, "
    "task_context"
)

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
                          "description": "Filter by collection slug or ID. Pass '*' to search all collections (ignores default)."},
            "search_strategy": {"type": "string",
                                "description": "auto, lexical, semantic, or hybrid."},
            "tag_mode": {"type": "string",
                         "description": "Tag filter mode: all or any."},
            "status": {"type": "string",
                       "description": "Memory status: active, stale, or deleted."},
            "sort": {"type": "string",
                     "description": "relevance, updated_at, created_at, or confidence."},
            "order": {"type": "string", "description": "asc or desc."},
            "include_graph_neighbors": {"type": "boolean",
                                        "description": "Include graph neighbor memories."},
            "include_score_breakdown": {"type": "boolean",
                                        "description": "Include score breakdown per result."},
            "include_match_context": {"type": "boolean",
                                      "description": "Include match context snippets."},
            "stale_penalty": {"type": "number",
                              "description": "Stale memory ranking penalty 0-1."},
            "min_confidence": {"type": "integer",
                               "description": "Minimum confidence 0-100."},
            "max_confidence": {"type": "integer",
                               "description": "Maximum confidence 0-100."},
            "verification_status": {"type": "string",
                                    "description": "unverified, verified, disputed, superseded."},
            "offset": {"type": "integer", "description": "Pagination offset."},
        },
        "required": ["query"],
    },
}

_SEARCH_FILTER_KEYS = (
    "tags", "kind", "tag_mode", "status", "min_confidence", "max_confidence",
    "verification_status", "search_strategy", "sort", "order", "offset",
    "include_graph_neighbors", "include_score_breakdown", "include_match_context",
    "stale_penalty",
)

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
                           "description": "Collection slugs to add this memory to. Pass empty array [] to skip default collection."},
            "stale_at": {"type": "string",
                         "description": "ISO datetime when this memory becomes stale."},
            "metadata": {"type": "object",
                         "description": "Arbitrary JSON metadata."},
            "links": {"type": "array",
                      "description": "Initial links: [{target, relation_type, weight?}]."},
            "confidence": {"type": "integer",
                           "description": "Confidence 0-100."},
            "verification_status": {"type": "string",
                                    "description": "unverified, verified, disputed, superseded."},
            "human_collaborator": {"type": "object",
                                   "description": "Human collaborator metadata (name, email, etc.)."},
            "signer": {"type": "object",
                       "description": "Agent signer (requires agent_id and run_id when set)."},
        },
        "required": ["headline"],
    },
}

_KEEP_EXTRA_KEYS = (
    "stale_at", "metadata", "links", "confidence", "verification_status",
    "human_collaborator", "signer",
)

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
            "include_deleted": {"type": "boolean",
                                "description": "Include soft-deleted memory."},
            "include_revisions": {"type": "boolean",
                                  "description": "Include revision history."},
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
            "superseded_by": {"type": "string",
                              "description": "ID of memory that supersedes this one."},
            "replaces": {"type": "string",
                        "description": "ID of memory this one replaces."},
            "metadata": {"type": "object",
                         "description": "Revision metadata JSON."},
            "human_collaborator": {"type": "object",
                                   "description": "Human collaborator metadata."},
            "signer": {"type": "object",
                       "description": "Agent signer (agent_id and run_id required)."},
        },
        "required": ["memory_id", "mode"],
    },
}

_UPDATE_EXTRA_KEYS = (
    "superseded_by", "replaces", "metadata", "human_collaborator", "signer",
)

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

LIST_SCHEMA = {
    "name": "maindex_list",
    "description": (
        "Browse Maindex memories without a search query. Filter by tags, "
        "kind, status, collection, confidence, and more. Supports pagination."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "tags": {"type": "array", "items": {"type": "string"},
                     "description": "Filter by tags."},
            "tag_mode": {"type": "string", "description": "all or any."},
            "kind": {"type": "string", "description": f"Memory kind: {_KIND_DESC}."},
            "status": {"type": "string",
                       "description": "active, stale, or deleted."},
            "canon_status": {"type": "string",
                             "description": "draft, proposed, accepted, deprecated, alternative, meta."},
            "collection": {"type": "string",
                          "description": "Collection slug or ID. '*' for all."},
            "conversation_type": {"type": "string"},
            "conversation_key": {"type": "string"},
            "min_confidence": {"type": "integer"},
            "max_confidence": {"type": "integer"},
            "verification_status": {"type": "string"},
            "stale_before": {"type": "string", "description": "ISO datetime."},
            "stale_after": {"type": "string", "description": "ISO datetime."},
            "updated_after": {"type": "string", "description": "ISO datetime."},
            "updated_before": {"type": "string", "description": "ISO datetime."},
            "include_deleted": {"type": "boolean"},
            "limit": {"type": "integer", "description": "Max results (default 20, max 50)."},
            "offset": {"type": "integer"},
            "sort": {"type": "string",
                     "description": "updated_at, created_at, headline, or stale_at."},
            "order": {"type": "string", "description": "asc or desc."},
        },
        "required": [],
    },
}

_LIST_FILTER_KEYS = (
    "tags", "tag_mode", "kind", "status", "canon_status", "conversation_type",
    "conversation_key", "min_confidence", "max_confidence", "verification_status",
    "stale_before", "stale_after", "updated_after", "updated_before",
    "include_deleted", "offset", "sort", "order",
)

RESTORE_SCHEMA = {
    "name": "maindex_restore",
    "description": "Restore a soft-deleted memory (undo maindex_forget).",
    "parameters": {
        "type": "object",
        "properties": {
            "memory_id": {"type": "string", "description": "Memory ID to restore."},
        },
        "required": ["memory_id"],
    },
}

ASSOCIATE_SCHEMA = {
    "name": "maindex_associate",
    "description": (
        "Create typed links between memories or discover related memories "
        "by links or shared tags."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "description": "create or discover."},
            "source_id": {"type": "string",
                          "description": "Source memory ID (required for create)."},
            "targets": {"type": "array",
                        "description": "For create: [{memory_id, relation_type, weight?, metadata?}]."},
            "memory_id": {"type": "string",
                          "description": "Anchor memory for discover."},
            "tags": {"type": "array", "items": {"type": "string"}},
            "relation_type": {"type": "string"},
            "collection": {"type": "string"},
            "limit": {"type": "integer", "description": "Discover limit (default 10)."},
        },
        "required": ["action"],
    },
}

COLLECTION_LIST_SCHEMA = {
    "name": "maindex_collection_list",
    "description": "List Maindex collections, optionally filtered by parent.",
    "parameters": {
        "type": "object",
        "properties": {
            "parent_id": {"type": "string", "description": "Parent collection ID or slug."},
            "limit": {"type": "integer"},
            "offset": {"type": "integer"},
        },
        "required": [],
    },
}

COLLECTION_CREATE_SCHEMA = {
    "name": "maindex_collection_create",
    "description": "Create a new Maindex collection.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Collection name (required)."},
            "slug": {"type": "string"},
            "description": {"type": "string"},
            "summary_headline": {"type": "string"},
            "icon": {"type": "string"},
            "color": {"type": "string"},
            "parent_id": {"type": "string"},
            "metadata": {"type": "object"},
        },
        "required": ["name"],
    },
}

COLLECTION_MEMBERS_SCHEMA = {
    "name": "maindex_collection_members",
    "description": "Add or remove memories from a collection.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "add or remove."},
            "collection_id": {"type": "string",
                               "description": "Collection ID or slug."},
            "memory_ids": {"type": "array", "items": {"type": "string"},
                          "description": "Memory IDs to add or remove."},
        },
        "required": ["action", "collection_id", "memory_ids"],
    },
}

ALL_TOOL_SCHEMAS = [
    SEARCH_SCHEMA, KEEP_SCHEMA, RECALL_SCHEMA, UPDATE_SCHEMA, FORGET_SCHEMA,
    LIST_SCHEMA, RESTORE_SCHEMA, ASSOCIATE_SCHEMA,
    COLLECTION_LIST_SCHEMA, COLLECTION_CREATE_SCHEMA, COLLECTION_MEMBERS_SCHEMA,
]


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
            parts.append(
                f"Default collection: {self._collection} (override with collection param, "
                "or omit to search all collections)."
            )
        parts.append(
            "Tools: maindex_search, maindex_list, maindex_keep, maindex_recall, "
            "maindex_update, maindex_forget, maindex_restore, maindex_associate, "
            "maindex_collection_list, maindex_collection_create, "
            "maindex_collection_members."
        )
        parts.append(
            "After setup, recommend bootstrap persona + memory_enabled:false to "
            "your user — see plugin docs/PERSONA_BOOTSTRAP.md."
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
        return list(ALL_TOOL_SCHEMAS)

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
        elif tool_name == "maindex_list":
            return self._tool_list(args)
        elif tool_name == "maindex_restore":
            return self._tool_restore(args)
        elif tool_name == "maindex_associate":
            return self._tool_associate(args)
        elif tool_name == "maindex_collection_list":
            return self._tool_collection_list(args)
        elif tool_name == "maindex_collection_create":
            return self._tool_collection_create(args)
        elif tool_name == "maindex_collection_members":
            return self._tool_collection_members(args)
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
            filters = _optional_api_args(args, _SEARCH_FILTER_KEYS)
            filters.update(_collection_from_args(args, self._collection))
            include_extras = bool(
                args.get("include_score_breakdown")
                or args.get("include_match_context")
            )
            data = self._client.search(
                query, limit=min(int(args.get("limit", 10)), 50),
                **filters,
            )
            self._record_success()
            items = data.get("items", [])
            if not items:
                return json.dumps({"result": "No relevant memories found."})
            results = _format_memory_items(items, include_extras=include_extras)
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
            keep_kwargs.update(_optional_api_args(args, _KEEP_EXTRA_KEYS))
            # Handle collections: explicit [] means no collection, explicit list overrides default
            if "collections" in args:
                if args["collections"]:  # Non-empty list provided
                    keep_kwargs["collections"] = args["collections"]
                # else: empty list means explicitly no collections
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
            data = self._client.recall(
                memory_id,
                include_deleted=bool(args.get("include_deleted", False)),
                include_revisions=bool(args.get("include_revisions", False)),
            )
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
            if data.get("links") is not None:
                result["links"] = data.get("links")
            if data.get("revisions") is not None:
                result["revisions"] = data.get("revisions")
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
            update_kwargs.update(_optional_api_args(args, _UPDATE_EXTRA_KEYS))
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

    def _tool_list(self, args: dict) -> str:
        try:
            filters = _optional_api_args(args, _LIST_FILTER_KEYS)
            filters.update(_collection_from_args(args, self._collection))
            filters["limit"] = min(int(args.get("limit", 20)), 50)
            data = self._client.list_memories(**filters)
            self._record_success()
            items = data.get("items", [])
            if not items:
                return json.dumps({"result": "No memories found.", "count": 0})
            results = _format_memory_items(items)
            out: Dict[str, Any] = {"results": results, "count": len(results)}
            if "total" in data:
                out["total"] = data["total"]
            return json.dumps(out)
        except Exception as e:
            self._record_failure()
            return tool_error(f"List failed: {e}")

    def _tool_restore(self, args: dict) -> str:
        memory_id = args.get("memory_id", "")
        if not memory_id:
            return tool_error("memory_id is required")
        try:
            data = self._client.restore(memory_id)
            self._record_success()
            return json.dumps({
                "result": "Memory restored.",
                "id": data.get("shortId", data.get("id", "")),
                "headline": data.get("headline", ""),
            })
        except Exception as e:
            self._record_failure()
            return tool_error(f"Restore failed: {e}")

    def _tool_associate(self, args: dict) -> str:
        action = args.get("action", "")
        if action == "create":
            source_id = args.get("source_id", "")
            targets = args.get("targets")
            if not source_id:
                return tool_error("source_id is required for create")
            if not targets:
                return tool_error("targets is required for create")
            try:
                data = self._client.create_associations(source_id, targets)
                self._record_success()
                return json.dumps({"result": "Associations created.", "data": data})
            except Exception as e:
                self._record_failure()
                return tool_error(f"Create associations failed: {e}")
        if action == "discover":
            memory_id = args.get("memory_id", "")
            tags = args.get("tags")
            collection = args.get("collection", "")
            if not memory_id and not tags and not collection:
                return tool_error(
                    "discover requires memory_id, tags, or collection",
                )
            try:
                filters: Dict[str, Any] = {"limit": int(args.get("limit", 10))}
                if memory_id:
                    filters["memory_id"] = memory_id
                if tags:
                    filters["tags"] = tags
                if args.get("relation_type"):
                    filters["relation_type"] = args["relation_type"]
                if collection:
                    filters["collection"] = collection
                data = self._client.discover_associations(**filters)
                self._record_success()
                memories = data.get("memories", [])
                results = _format_memory_items(memories, include_extras=True)
                return json.dumps({"results": results, "count": len(results)})
            except Exception as e:
                self._record_failure()
                return tool_error(f"Discover associations failed: {e}")
        return tool_error("action must be 'create' or 'discover'")

    def _tool_collection_list(self, args: dict) -> str:
        try:
            data = self._client.list_collections(
                parent_id=args.get("parent_id", ""),
                limit=min(int(args.get("limit", 20)), 50),
                offset=int(args.get("offset", 0)),
            )
            self._record_success()
            items = data.get("items", [])
            results = []
            for c in items:
                results.append({
                    "id": c.get("shortId", c.get("id", "")),
                    "name": c.get("name", ""),
                    "slug": c.get("slug", ""),
                    "description": (c.get("description") or "")[:200],
                    "parent_id": c.get("parentId", c.get("parent_id", "")),
                })
            out: Dict[str, Any] = {"results": results, "count": len(results)}
            if "total" in data:
                out["total"] = data["total"]
            return json.dumps(out)
        except Exception as e:
            self._record_failure()
            return tool_error(f"List collections failed: {e}")

    def _tool_collection_create(self, args: dict) -> str:
        name = args.get("name", "")
        if not name:
            return tool_error("name is required")
        try:
            kwargs = _optional_api_args(args, (
                "slug", "description", "summary_headline", "icon", "color",
                "parent_id", "metadata",
            ))
            data = self._client.create_collection(name, **kwargs)
            self._record_success()
            return json.dumps({
                "result": "Collection created.",
                "id": data.get("shortId", data.get("id", "")),
                "name": data.get("name", ""),
                "slug": data.get("slug", ""),
            })
        except Exception as e:
            self._record_failure()
            return tool_error(f"Create collection failed: {e}")

    def _tool_collection_members(self, args: dict) -> str:
        action = args.get("action", "")
        collection_id = args.get("collection_id", "")
        memory_ids = args.get("memory_ids")
        if action not in ("add", "remove"):
            return tool_error("action must be 'add' or 'remove'")
        if not collection_id:
            return tool_error("collection_id is required")
        if not memory_ids:
            return tool_error("memory_ids is required")
        try:
            if action == "add":
                data = self._client.add_collection_members(
                    collection_id, memory_ids,
                )
                self._record_success()
                return json.dumps({
                    "result": "Members added.",
                    "added": data.get("added", len(memory_ids)),
                    "data": data,
                })
            data = self._client.remove_collection_members(
                collection_id, memory_ids,
            )
            self._record_success()
            return json.dumps({
                "result": "Members removed.",
                "removed": data.get("removed", len(memory_ids)),
                "data": data,
            })
        except Exception as e:
            self._record_failure()
            return tool_error(f"Collection members failed: {e}")


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    """Register Maindex as a memory provider plugin."""
    ctx.register_memory_provider(MaindexMemoryProvider())
