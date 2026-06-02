"""
Unit tests for Google Sheets reorder_sheet tool.
"""

import pytest
from unittest.mock import Mock
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from gsheets.sheets_tools import _reorder_sheet_impl
from core.utils import UserInputError


def create_mock_service(sheets_metadata=None):
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
async def test_reorder_by_id():
    mock_service = create_mock_service()
    mock_service.spreadsheets().get = Mock()

    result = await _reorder_sheet_impl(
        service=mock_service,
        spreadsheet_id="ssid",
        new_index=2,
        sheet_id=123,
    )

    call_args = mock_service.spreadsheets().batchUpdate.call_args
    body = call_args[1]["body"]
    req = body["requests"][0]["updateSheetProperties"]
    assert req["properties"]["sheetId"] == 123
    assert req["properties"]["index"] == 2
    assert req["fields"] == "index"
    mock_service.spreadsheets().get.assert_not_called()
    assert "123" in result
    assert "2" in result


@pytest.mark.asyncio
async def test_reorder_by_name():
    mock_service = create_mock_service()

    result = await _reorder_sheet_impl(
        service=mock_service,
        spreadsheet_id="ssid",
        new_index=1,
        sheet_name="Data",
    )

    call_args = mock_service.spreadsheets().batchUpdate.call_args
    body = call_args[1]["body"]
    req = body["requests"][0]["updateSheetProperties"]
    assert req["properties"]["sheetId"] == 123
    assert req["properties"]["index"] == 1
    assert req["fields"] == "index"
    assert "Data" in result


@pytest.mark.asyncio
async def test_reorder_id_wins_when_both_provided():
    mock_service = create_mock_service()
    mock_service.spreadsheets().get = Mock()

    await _reorder_sheet_impl(
        service=mock_service,
        spreadsheet_id="ssid",
        new_index=3,
        sheet_name="Data",
        sheet_id=999,
    )

    call_args = mock_service.spreadsheets().batchUpdate.call_args
    body = call_args[1]["body"]
    req = body["requests"][0]["updateSheetProperties"]
    assert req["properties"]["sheetId"] == 999
    assert req["properties"]["index"] == 3
    mock_service.spreadsheets().get.assert_not_called()


@pytest.mark.asyncio
async def test_reorder_unknown_name_raises():
    mock_service = create_mock_service()

    with pytest.raises(UserInputError) as exc_info:
        await _reorder_sheet_impl(
            service=mock_service,
            spreadsheet_id="ssid",
            new_index=0,
            sheet_name="Missing",
        )

    msg = str(exc_info.value)
    assert "Missing" in msg


@pytest.mark.asyncio
async def test_reorder_no_identifier_raises():
    mock_service = create_mock_service()

    with pytest.raises(UserInputError):
        await _reorder_sheet_impl(
            service=mock_service,
            spreadsheet_id="ssid",
            new_index=0,
        )


@pytest.mark.asyncio
async def test_reorder_index_zero():
    mock_service = create_mock_service()

    await _reorder_sheet_impl(
        service=mock_service,
        spreadsheet_id="ssid",
        new_index=0,
        sheet_id=123,
    )

    call_args = mock_service.spreadsheets().batchUpdate.call_args
    body = call_args[1]["body"]
    req = body["requests"][0]["updateSheetProperties"]
    assert req["properties"]["index"] == 0
    assert req["fields"] == "index"
