"""
Unit tests for Google Sheets duplicate_sheet tool.
"""

import pytest
from unittest.mock import Mock
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from gsheets.sheets_tools import _duplicate_sheet_impl
from core.utils import UserInputError


DEFAULT_DUPLICATE_REPLY = {
    "replies": [
        {
            "duplicateSheet": {
                "properties": {"sheetId": 999, "title": "Copy of Data"}
            }
        }
    ]
}


def create_mock_service(sheets_metadata=None, batch_reply=None):
    if sheets_metadata is None:
        sheets_metadata = {
            "sheets": [
                {"properties": {"sheetId": 0, "title": "Sheet1"}},
                {"properties": {"sheetId": 123, "title": "Data"}},
            ]
        }
    if batch_reply is None:
        batch_reply = DEFAULT_DUPLICATE_REPLY
    mock_service = Mock()
    mock_service.spreadsheets().get().execute = Mock(return_value=sheets_metadata)
    mock_service.spreadsheets().batchUpdate().execute = Mock(return_value=batch_reply)
    return mock_service


@pytest.mark.asyncio
async def test_duplicate_sheet_by_id():
    mock_service = create_mock_service()
    mock_service.spreadsheets().get = Mock()

    await _duplicate_sheet_impl(
        service=mock_service,
        spreadsheet_id="ssid",
        sheet_id=123,
    )

    call_args = mock_service.spreadsheets().batchUpdate.call_args
    body = call_args[1]["body"]
    assert body["requests"] == [{"duplicateSheet": {"sourceSheetId": 123}}]
    mock_service.spreadsheets().get.assert_not_called()


@pytest.mark.asyncio
async def test_duplicate_sheet_by_name():
    mock_service = create_mock_service()

    await _duplicate_sheet_impl(
        service=mock_service,
        spreadsheet_id="ssid",
        sheet_name="Data",
    )

    call_args = mock_service.spreadsheets().batchUpdate.call_args
    body = call_args[1]["body"]
    assert body["requests"] == [{"duplicateSheet": {"sourceSheetId": 123}}]


@pytest.mark.asyncio
async def test_duplicate_sheet_with_new_name_and_index():
    mock_service = create_mock_service()

    await _duplicate_sheet_impl(
        service=mock_service,
        spreadsheet_id="ssid",
        sheet_id=123,
        new_sheet_name="MyCopy",
        insert_index=2,
    )

    call_args = mock_service.spreadsheets().batchUpdate.call_args
    body = call_args[1]["body"]
    req = body["requests"][0]["duplicateSheet"]
    assert req["sourceSheetId"] == 123
    assert req["newSheetName"] == "MyCopy"
    assert req["insertSheetIndex"] == 2


@pytest.mark.asyncio
async def test_duplicate_sheet_returns_new_sheet_info():
    mock_service = create_mock_service()

    result = await _duplicate_sheet_impl(
        service=mock_service,
        spreadsheet_id="ssid",
        sheet_id=123,
    )

    assert "999" in result
    assert "Copy of Data" in result


@pytest.mark.asyncio
async def test_duplicate_sheet_unknown_name_raises():
    mock_service = create_mock_service()

    with pytest.raises(UserInputError) as exc_info:
        await _duplicate_sheet_impl(
            service=mock_service,
            spreadsheet_id="ssid",
            sheet_name="Missing",
        )

    assert "Missing" in str(exc_info.value)


@pytest.mark.asyncio
async def test_duplicate_sheet_no_identifier_raises():
    mock_service = create_mock_service()

    with pytest.raises(UserInputError):
        await _duplicate_sheet_impl(
            service=mock_service,
            spreadsheet_id="ssid",
        )
