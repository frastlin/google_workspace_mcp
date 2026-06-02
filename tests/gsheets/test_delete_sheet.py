"""
Unit tests for Google Sheets delete_sheet tool.
"""

import pytest
from unittest.mock import Mock
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from gsheets.sheets_tools import _delete_sheet_impl
from core.utils import UserInputError


def create_mock_service(sheets_metadata=None):
    """Mock service. By default returns Sheet1 (id=0) and Data (id=123)."""
    if sheets_metadata is None:
        sheets_metadata = {
            "sheets": [
                {"properties": {"sheetId": 0, "title": "Sheet1"}},
                {"properties": {"sheetId": 123, "title": "Data"}},
            ]
        }
    mock_service = Mock()
    mock_service.spreadsheets().get().execute = Mock(return_value=sheets_metadata)
    mock_service.spreadsheets().batchUpdate().execute = Mock(return_value={})
    return mock_service


@pytest.mark.asyncio
async def test_delete_sheet_by_id():
    mock_service = create_mock_service()
    mock_service.spreadsheets().get = Mock()

    result = await _delete_sheet_impl(
        service=mock_service,
        spreadsheet_id="ssid",
        sheet_id=123,
    )

    call_args = mock_service.spreadsheets().batchUpdate.call_args
    body = call_args[1]["body"]
    assert body["requests"] == [{"deleteSheet": {"sheetId": 123}}]
    mock_service.spreadsheets().get.assert_not_called()
    assert "123" in result


@pytest.mark.asyncio
async def test_delete_sheet_by_name():
    mock_service = create_mock_service()

    result = await _delete_sheet_impl(
        service=mock_service,
        spreadsheet_id="ssid",
        sheet_name="Data",
    )

    call_args = mock_service.spreadsheets().batchUpdate.call_args
    body = call_args[1]["body"]
    assert body["requests"] == [{"deleteSheet": {"sheetId": 123}}]
    assert "Data" in result


@pytest.mark.asyncio
async def test_delete_sheet_unknown_name_raises():
    mock_service = create_mock_service()

    with pytest.raises(UserInputError) as exc_info:
        await _delete_sheet_impl(
            service=mock_service,
            spreadsheet_id="ssid",
            sheet_name="DoesNotExist",
        )

    msg = str(exc_info.value)
    assert "DoesNotExist" in msg
    assert "Sheet1" in msg
    assert "Data" in msg


@pytest.mark.asyncio
async def test_delete_sheet_no_identifier_raises():
    mock_service = create_mock_service()

    with pytest.raises(UserInputError):
        await _delete_sheet_impl(
            service=mock_service,
            spreadsheet_id="ssid",
        )


@pytest.mark.asyncio
async def test_delete_sheet_id_wins_when_both_provided():
    mock_service = create_mock_service()
    mock_service.spreadsheets().get = Mock()

    await _delete_sheet_impl(
        service=mock_service,
        spreadsheet_id="ssid",
        sheet_name="Data",
        sheet_id=999,
    )

    call_args = mock_service.spreadsheets().batchUpdate.call_args
    body = call_args[1]["body"]
    assert body["requests"] == [{"deleteSheet": {"sheetId": 999}}]
    mock_service.spreadsheets().get.assert_not_called()
