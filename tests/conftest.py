"""Stubs hermes-agent dependencies and loads the plugin for isolated testing.

The plugin imports from agent.memory_provider, tools.registry, and
hermes_constants — packages that live in the hermes-agent repo.  We inject
minimal stubs into sys.modules so the plugin module can be loaded without
a full hermes-agent installation.
"""

import importlib.util
import json
import sys
import types
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

# ── Hermes dependency stubs (must be registered before plugin import) ────

_agent = types.ModuleType("agent")
_agent_mp = types.ModuleType("agent.memory_provider")


class _MemoryProvider(ABC):
    """Matches the real MemoryProvider ABC surface used by the plugin."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def initialize(self, session_id: str, **kwargs) -> None: ...

    def system_prompt_block(self) -> str:
        return ""

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        return ""

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        pass

    def sync_turn(
        self, user_content: str, assistant_content: str, *, session_id: str = ""
    ) -> None:
        pass

    def on_memory_write(
        self, action: str, target: str, content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        pass

    def on_pre_compress(self, messages: List[Dict[str, Any]]) -> str:
        return ""

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return []

    def handle_tool_call(self, tool_name: str, args: dict, **kwargs) -> str:
        return ""

    def shutdown(self) -> None:
        pass

    def get_config_schema(self) -> list:
        return []

    def save_config(self, values: Dict[str, Any], hermes_home: str) -> None:
        pass


_agent_mp.MemoryProvider = _MemoryProvider
sys.modules["agent"] = _agent
sys.modules["agent.memory_provider"] = _agent_mp

_tools = types.ModuleType("tools")
_tools_reg = types.ModuleType("tools.registry")


def _tool_error(message, **extra) -> str:
    result: Dict[str, Any] = {"error": str(message)}
    if extra:
        result.update(extra)
    return json.dumps(result, ensure_ascii=False)


_tools_reg.tool_error = _tool_error
sys.modules["tools"] = _tools
sys.modules["tools.registry"] = _tools_reg

_hc = types.ModuleType("hermes_constants")
_hc.get_hermes_home = lambda: Path("/tmp/test-hermes-home")
sys.modules["hermes_constants"] = _hc

# ── Load the plugin module under a clean name ────────────────────────────

_plugin_path = str(Path(__file__).resolve().parent.parent / "__init__.py")
_spec = importlib.util.spec_from_file_location("maindex_plugin", _plugin_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
sys.modules["maindex_plugin"] = _mod


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def provider():
    """Fresh MaindexMemoryProvider with a mock client pre-injected.

    Returns (provider, mock_client) so tests can set up return values
    on mock_client methods and assert calls.
    """
    p = _mod.MaindexMemoryProvider()
    mock_client = MagicMock()
    p._client = mock_client
    p._session_id = "sess-001"
    p._config = {"api_key": "k", "token": "", "collection": ""}
    return p, mock_client
