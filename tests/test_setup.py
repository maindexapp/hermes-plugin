"""Tests for setup wizard and CLI helpers."""

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from maindex_hermes_plugin.setup import (
    activate_memory_provider,
    mask_secret,
    run_setup_wizard,
    test_connection as verify_connection,
    write_env_vars,
)


def _stub_hermes_cli_config(load_return=None, save_side_effect=None):
    hc_mod = types.ModuleType("hermes_cli")
    hc_cfg = types.ModuleType("hermes_cli.config")
    hc_cfg.load_config = lambda: load_return or {"memory": {}}
    if save_side_effect is not None:
        hc_cfg.save_config = save_side_effect
    else:
        hc_cfg.save_config = lambda config: None
    sys.modules["hermes_cli"] = hc_mod
    sys.modules["hermes_cli.config"] = hc_cfg


class TestMaskSecret:

    def test_empty(self):
        assert mask_secret("") == "not set"

    def test_short_value(self):
        assert mask_secret("abc") == "set"

    def test_long_value(self):
        assert mask_secret("idx_1234567890abcdef") == "...90abcdef"


class TestWriteEnvVars:

    def test_creates_and_updates_env_file(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("OTHER=value\nMAINDEX_API_KEY=old\n")

        write_env_vars(env_path, {"MAINDEX_API_KEY": "new-key"})

        lines = env_path.read_text(encoding="utf-8").splitlines()
        assert "OTHER=value" in lines
        assert "MAINDEX_API_KEY=new-key" in lines
        assert "MAINDEX_API_KEY=old" not in lines

    def test_appends_missing_keys(self, tmp_path):
        env_path = tmp_path / ".env"
        write_env_vars(env_path, {"MAINDEX_API_KEY": "fresh"})
        assert env_path.read_text(encoding="utf-8").strip() == "MAINDEX_API_KEY=fresh"


class TestActivateMemoryProvider:

    def test_sets_provider_in_config(self):
        saved = {}

        def fake_save(config):
            saved["config"] = config

        _stub_hermes_cli_config(save_side_effect=fake_save)
        activate_memory_provider()

        assert saved["config"]["memory"]["provider"] == "maindex"


class TestConnection:

    def test_fails_without_credentials(self):
        ok, message = verify_connection()
        assert ok is False
        assert "No credentials" in message

    def test_success(self, monkeypatch):
        mock_client = MagicMock()
        mock_client.list_memories.return_value = {"items": []}
        with patch("maindex_hermes_plugin.setup.MaindexClient", return_value=mock_client):
            ok, message = verify_connection(api_key="test-key")
        assert ok is True
        mock_client.close.assert_called_once()

    def test_failure(self, monkeypatch):
        mock_client = MagicMock()
        mock_client.list_memories.side_effect = RuntimeError("401 Unauthorized")
        with patch("maindex_hermes_plugin.setup.MaindexClient", return_value=mock_client):
            ok, message = verify_connection(api_key="bad-key")
        assert ok is False
        assert "401" in message


class TestSetupWizard:

    def test_prompts_and_activates_with_new_key(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            sys.modules["hermes_constants"], "get_hermes_home", lambda: tmp_path,
        )
        monkeypatch.delenv("MAINDEX_API_KEY", raising=False)
        monkeypatch.delenv("MAINDEX_TOKEN", raising=False)

        inputs = iter(["new-api-key", ""])
        monkeypatch.setattr(
            "maindex_hermes_plugin.setup._prompt",
            lambda *args, **kwargs: next(inputs),
        )

        saved_config = {}

        def fake_save(config):
            saved_config["value"] = config

        _stub_hermes_cli_config(save_side_effect=fake_save)

        with patch(
            "maindex_hermes_plugin.setup.test_connection",
            return_value=(True, "Connected successfully"),
        ):
            assert run_setup_wizard(str(tmp_path)) is True

        env_text = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "MAINDEX_API_KEY=new-api-key" in env_text
        assert saved_config["value"]["memory"]["provider"] == "maindex"

    def test_returns_false_without_credentials(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            sys.modules["hermes_constants"], "get_hermes_home", lambda: tmp_path,
        )
        monkeypatch.delenv("MAINDEX_API_KEY", raising=False)
        monkeypatch.delenv("MAINDEX_TOKEN", raising=False)

        monkeypatch.setattr(
            "maindex_hermes_plugin.setup._prompt",
            lambda *args, **kwargs: "",
        )

        assert run_setup_wizard(str(tmp_path)) is False


class TestCli:

    @pytest.fixture(autouse=True)
    def _stub_cli_deps(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MAINDEX_API_KEY", "cli-test-key")
        monkeypatch.setattr(
            sys.modules["hermes_constants"], "get_hermes_home", lambda: tmp_path,
        )

        hc_mod = types.ModuleType("hermes_cli")
        hc_cfg = types.ModuleType("hermes_cli.config")
        hc_cfg.load_config = lambda: {"memory": {"provider": "maindex"}}
        hc_cfg.save_config = lambda config: None
        sys.modules["hermes_cli"] = hc_mod
        sys.modules["hermes_cli.config"] = hc_cfg

        cli_path = Path(__file__).resolve().parent.parent / "cli.py"
        import importlib.util

        spec = importlib.util.spec_from_file_location("maindex_cli", cli_path)
        cli_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli_mod)
        self.cli = cli_mod

    def test_status_reports_connected(self, capsys):
        with patch.object(
            self.cli,
            "test_connection",
            return_value=(True, "Connected successfully"),
        ):
            self.cli.cmd_status(types.SimpleNamespace())
        out = capsys.readouterr().out
        assert "Memory provider: maindex" in out
        assert "Connection... OK" in out

    def test_test_exits_nonzero_on_failure(self):
        with patch.object(
            self.cli,
            "test_connection",
            return_value=(False, "401 Unauthorized"),
        ):
            with pytest.raises(SystemExit) as exc:
                self.cli.cmd_test(types.SimpleNamespace())
        assert exc.value.code == 1
