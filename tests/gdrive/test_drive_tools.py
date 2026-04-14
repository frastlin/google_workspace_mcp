"""
Unit tests for Google Drive MCP tools.

Tests create_drive_folder with mocked API responses.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


@pytest.mark.asyncio
async def test_create_drive_folder():
    """Test create_drive_folder returns success message with folder id, name, and link."""
    from gdrive.drive_tools import _create_drive_folder_impl

    mock_service = Mock()
    mock_response = {
        "id": "folder123",
        "name": "My Folder",
        "webViewLink": "https://drive.google.com/drive/folders/folder123",
    }
    mock_request = Mock()
    mock_request.execute.return_value = mock_response
    mock_service.files.return_value.create.return_value = mock_request

    with patch(
        "gdrive.drive_tools.resolve_folder_id",
        new_callable=AsyncMock,
        return_value="root",
    ):
        result = await _create_drive_folder_impl(
            service=mock_service,
            user_google_email="user@example.com",
            folder_name="My Folder",
            parent_folder_id="root",
        )

    assert "Successfully created folder" in result
    assert "My Folder" in result
    assert "folder123" in result
    assert "user@example.com" in result
    assert "https://drive.google.com/drive/folders/folder123" in result


@pytest.mark.asyncio
async def test_create_drive_shortcut_with_name():
    """Test _create_drive_shortcut_impl with an explicit name."""
    from gdrive.drive_tools import _create_drive_shortcut_impl

    mock_service = Mock()
    mock_response = {
        "id": "shortcut456",
        "name": "My Shortcut",
        "webViewLink": "https://drive.google.com/file/d/shortcut456/view",
        "shortcutDetails": {"targetId": "target789"},
    }
    mock_request = Mock()
    mock_request.execute.return_value = mock_response
    mock_service.files.return_value.create.return_value = mock_request

    with patch(
        "gdrive.drive_tools.resolve_folder_id",
        new_callable=AsyncMock,
        return_value="parent_resolved",
    ):
        result = await _create_drive_shortcut_impl(
            service=mock_service,
            user_google_email="user@example.com",
            target_id="target789",
            folder_id="parent_folder",
            name="My Shortcut",
        )

    assert "Successfully created shortcut" in result
    assert "My Shortcut" in result
    assert "shortcut456" in result
    assert "target789" in result
    assert "user@example.com" in result

    # Verify the API call metadata
    call_kwargs = mock_service.files().create.call_args
    body = call_kwargs.kwargs.get("body") or call_kwargs[1].get("body")
    assert body["mimeType"] == "application/vnd.google-apps.shortcut"
    assert body["shortcutDetails"]["targetId"] == "target789"
    assert body["parents"] == ["parent_resolved"]
    assert body["name"] == "My Shortcut"


@pytest.mark.asyncio
async def test_create_drive_shortcut_without_name():
    """Test _create_drive_shortcut_impl without a name (Drive auto-names after target)."""
    from gdrive.drive_tools import _create_drive_shortcut_impl

    mock_service = Mock()
    mock_response = {
        "id": "shortcut456",
        "name": "Auto Named Target",
        "webViewLink": "https://drive.google.com/file/d/shortcut456/view",
        "shortcutDetails": {"targetId": "target789"},
    }
    mock_request = Mock()
    mock_request.execute.return_value = mock_response
    mock_service.files.return_value.create.return_value = mock_request

    with patch(
        "gdrive.drive_tools.resolve_folder_id",
        new_callable=AsyncMock,
        return_value="root",
    ):
        result = await _create_drive_shortcut_impl(
            service=mock_service,
            user_google_email="user@example.com",
            target_id="target789",
        )

    assert "Successfully created shortcut" in result
    assert "shortcut456" in result

    # Verify "name" key is NOT in the API body (Drive auto-names)
    call_kwargs = mock_service.files().create.call_args
    body = call_kwargs.kwargs.get("body") or call_kwargs[1].get("body")
    assert "name" not in body


@pytest.mark.asyncio
async def test_create_drive_shortcut_folder_resolution():
    """Test that resolve_folder_id is called and the resolved ID is used."""
    from gdrive.drive_tools import _create_drive_shortcut_impl

    mock_service = Mock()
    mock_response = {
        "id": "shortcut456",
        "name": "Shortcut",
        "webViewLink": "https://drive.google.com/file/d/shortcut456/view",
        "shortcutDetails": {"targetId": "target789"},
    }
    mock_request = Mock()
    mock_request.execute.return_value = mock_response
    mock_service.files.return_value.create.return_value = mock_request

    with patch(
        "gdrive.drive_tools.resolve_folder_id",
        new_callable=AsyncMock,
        return_value="resolved_shared_drive_folder",
    ) as mock_resolve:
        await _create_drive_shortcut_impl(
            service=mock_service,
            user_google_email="user@example.com",
            target_id="target789",
            folder_id="shared_drive_folder",
            name="Shortcut",
        )

    mock_resolve.assert_called_once_with(mock_service, "shared_drive_folder")
    call_kwargs = mock_service.files().create.call_args
    body = call_kwargs.kwargs.get("body") or call_kwargs[1].get("body")
    assert body["parents"] == ["resolved_shared_drive_folder"]


@pytest.mark.asyncio
async def test_create_drive_file_delegates_to_shortcut():
    """Test that create_drive_file delegates to _create_drive_shortcut_impl for shortcut MIME type."""
    from gdrive.drive_tools import _create_drive_shortcut_impl
    from gdrive.drive_tools import create_drive_file

    mock_service = Mock()

    with patch(
        "gdrive.drive_tools._create_drive_shortcut_impl",
        new_callable=AsyncMock,
        return_value="shortcut created",
    ) as mock_shortcut_impl:
        result = await create_drive_file.__wrapped__.__wrapped__.__wrapped__(
            service=mock_service,
            user_google_email="user@example.com",
            file_name="My Link",
            mime_type="application/vnd.google-apps.shortcut",
            target_id="target789",
            folder_id="parent_folder",
        )

    assert result == "shortcut created"
    mock_shortcut_impl.assert_called_once_with(
        mock_service, "user@example.com", "target789", "parent_folder", "My Link",
    )
