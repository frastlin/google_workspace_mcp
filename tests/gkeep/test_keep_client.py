"""Tests for gkeep.keep_client module."""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gkeep.keep_client import (
    KeepAuthError,
    _get_credentials_dir,
    _get_keep_email,
    _get_token_path,
    _load_master_token,
    get_keep_client,
    login_and_save,
    reset_client,
    save_master_token,
)


@pytest.fixture(autouse=True)
def _reset():
    """Reset the singleton between tests."""
    reset_client()
    yield
    reset_client()


class TestGetCredentialsDir:
    def test_workspace_env(self, monkeypatch):
        monkeypatch.setenv("WORKSPACE_MCP_CREDENTIALS_DIR", "/tmp/creds")
        monkeypatch.delenv("GOOGLE_MCP_CREDENTIALS_DIR", raising=False)
        assert _get_credentials_dir() == "/tmp/creds"

    def test_google_env_fallback(self, monkeypatch):
        monkeypatch.delenv("WORKSPACE_MCP_CREDENTIALS_DIR", raising=False)
        monkeypatch.setenv("GOOGLE_MCP_CREDENTIALS_DIR", "/tmp/google-creds")
        assert _get_credentials_dir() == "/tmp/google-creds"

    def test_default(self, monkeypatch):
        monkeypatch.delenv("WORKSPACE_MCP_CREDENTIALS_DIR", raising=False)
        monkeypatch.delenv("GOOGLE_MCP_CREDENTIALS_DIR", raising=False)
        result = _get_credentials_dir()
        assert ".google_workspace_mcp" in result
        assert result.endswith("credentials")


class TestGetKeepEmail:
    def test_keep_email_env(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_KEEP_EMAIL", "keep@example.com")
        monkeypatch.delenv("USER_GOOGLE_EMAIL", raising=False)
        assert _get_keep_email() == "keep@example.com"

    def test_user_email_fallback(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_KEEP_EMAIL", raising=False)
        monkeypatch.setenv("USER_GOOGLE_EMAIL", "user@example.com")
        assert _get_keep_email() == "user@example.com"

    def test_no_email(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_KEEP_EMAIL", raising=False)
        monkeypatch.delenv("USER_GOOGLE_EMAIL", raising=False)
        assert _get_keep_email() is None


class TestLoadMasterToken:
    def test_env_var(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_KEEP_MASTER_TOKEN", "tok123")
        assert _load_master_token() == "tok123"

    def test_file(self, monkeypatch, tmp_path):
        monkeypatch.delenv("GOOGLE_KEEP_MASTER_TOKEN", raising=False)
        monkeypatch.setenv("WORKSPACE_MCP_CREDENTIALS_DIR", str(tmp_path))

        token_file = tmp_path / "keep_master_token.json"
        token_file.write_text(json.dumps({"master_token": "file_tok", "email": "a@b.com"}))

        assert _load_master_token() == "file_tok"

    def test_no_token(self, monkeypatch, tmp_path):
        monkeypatch.delenv("GOOGLE_KEEP_MASTER_TOKEN", raising=False)
        monkeypatch.setenv("WORKSPACE_MCP_CREDENTIALS_DIR", str(tmp_path))
        assert _load_master_token() is None


class TestSaveMasterToken:
    def test_saves_to_file(self, monkeypatch, tmp_path):
        monkeypatch.setenv("WORKSPACE_MCP_CREDENTIALS_DIR", str(tmp_path))
        path = save_master_token("tok_abc", "user@test.com")

        assert os.path.exists(path)
        with open(path) as f:
            data = json.load(f)
        assert data["master_token"] == "tok_abc"
        assert data["email"] == "user@test.com"


class TestGetKeepClient:
    @pytest.mark.asyncio
    async def test_no_email_raises(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_KEEP_EMAIL", raising=False)
        monkeypatch.delenv("USER_GOOGLE_EMAIL", raising=False)
        with pytest.raises(KeepAuthError, match="No email configured"):
            await get_keep_client()

    @pytest.mark.asyncio
    async def test_no_token_raises(self, monkeypatch, tmp_path):
        monkeypatch.setenv("USER_GOOGLE_EMAIL", "test@example.com")
        monkeypatch.delenv("GOOGLE_KEEP_MASTER_TOKEN", raising=False)
        monkeypatch.setenv("WORKSPACE_MCP_CREDENTIALS_DIR", str(tmp_path))
        with pytest.raises(KeepAuthError, match="not configured"):
            await get_keep_client()

    @pytest.mark.asyncio
    async def test_successful_auth(self, monkeypatch, tmp_path):
        monkeypatch.setenv("USER_GOOGLE_EMAIL", "test@example.com")
        monkeypatch.setenv("GOOGLE_KEEP_MASTER_TOKEN", "master_tok")

        mock_keep = MagicMock()
        mock_keep.resume.return_value = True
        mock_keep.sync.return_value = None

        with patch("gkeep.keep_client.gkeepapi.Keep", return_value=mock_keep):
            client = await get_keep_client()

        assert client is mock_keep
        mock_keep.resume.assert_called_once_with("test@example.com", "master_tok")
        mock_keep.sync.assert_called_once()

    @pytest.mark.asyncio
    async def test_singleton_returns_same_client(self, monkeypatch):
        monkeypatch.setenv("USER_GOOGLE_EMAIL", "test@example.com")
        monkeypatch.setenv("GOOGLE_KEEP_MASTER_TOKEN", "master_tok")

        mock_keep = MagicMock()
        mock_keep.resume.return_value = True
        mock_keep.sync.return_value = None

        with patch("gkeep.keep_client.gkeepapi.Keep", return_value=mock_keep):
            client1 = await get_keep_client()
            client2 = await get_keep_client()

        assert client1 is client2
        # resume should only be called once (singleton)
        mock_keep.resume.assert_called_once()


class TestLoginAndSave:
    @pytest.mark.asyncio
    async def test_login_success(self, monkeypatch, tmp_path):
        monkeypatch.setenv("WORKSPACE_MCP_CREDENTIALS_DIR", str(tmp_path))

        mock_keep = MagicMock()
        mock_keep.login.return_value = None
        mock_keep.getMasterToken.return_value = "new_master_tok"
        mock_keep.sync.return_value = None

        with patch("gkeep.keep_client.gkeepapi.Keep", return_value=mock_keep):
            result = await login_and_save("user@test.com", "app_password_here")

        assert "successful" in result
        assert "user@test.com" in result
        mock_keep.login.assert_called_once_with("user@test.com", "app_password_here")

        # Verify token was saved
        token_path = tmp_path / "keep_master_token.json"
        assert token_path.exists()
        data = json.loads(token_path.read_text())
        assert data["master_token"] == "new_master_tok"
