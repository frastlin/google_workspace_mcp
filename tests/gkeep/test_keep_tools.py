"""Tests for gkeep.keep_tools module (official Keep API).

Tests call the _impl functions directly to bypass MCP decorators.
Uses Mock service chain pattern to simulate googleapiclient responses.
"""

from unittest.mock import Mock

import pytest

from gkeep.keep_tools import (
    _create_keep_list_impl,
    _create_keep_note_impl,
    _delete_keep_note_impl,
    _get_keep_note_impl,
    _list_keep_notes_impl,
    _share_keep_note_impl,
    _format_note_summary,
    _format_note_detail,
)


# --- Fixtures ---


def _make_text_note(
    name="notes/note_1",
    title="Test Note",
    text="Hello world",
    trashed=False,
    create_time="2025-01-01T00:00:00Z",
    update_time="2025-01-02T00:00:00Z",
    permissions=None,
):
    note = {
        "name": name,
        "title": title,
        "body": {
            "text": {"text": text},
        },
        "trashed": trashed,
        "createTime": create_time,
        "updateTime": update_time,
    }
    if permissions:
        note["permissions"] = permissions
    return note


def _make_list_note(
    name="notes/list_1",
    title="Shopping",
    items=None,
    trashed=False,
    create_time="2025-01-01T00:00:00Z",
    update_time="2025-01-02T00:00:00Z",
):
    if items is None:
        items = []
    return {
        "name": name,
        "title": title,
        "body": {
            "list": {
                "listItems": items,
            }
        },
        "trashed": trashed,
        "createTime": create_time,
        "updateTime": update_time,
    }


def _make_list_item(text="Milk", checked=False):
    return {
        "text": {"text": text},
        "checked": checked,
    }


def _make_mock_service(list_response=None, get_response=None, create_response=None, delete_response=None, permissions_response=None):
    """Create a mock Google Keep API service."""
    service = Mock()

    # notes().list()
    mock_list_request = Mock()
    mock_list_request.execute.return_value = list_response or {"notes": []}
    service.notes.return_value.list.return_value = mock_list_request

    # notes().get()
    mock_get_request = Mock()
    mock_get_request.execute.return_value = get_response or {}
    service.notes.return_value.get.return_value = mock_get_request

    # notes().create()
    mock_create_request = Mock()
    mock_create_request.execute.return_value = create_response or {}
    service.notes.return_value.create.return_value = mock_create_request

    # notes().delete()
    mock_delete_request = Mock()
    mock_delete_request.execute.return_value = delete_response or {}
    service.notes.return_value.delete.return_value = mock_delete_request

    # notes().permissions().batchCreate()
    mock_perm_request = Mock()
    mock_perm_request.execute.return_value = permissions_response or {"permissions": []}
    service.notes.return_value.permissions.return_value.batchCreate.return_value = mock_perm_request

    return service


# ============================================================
# Formatting tests
# ============================================================


class TestFormatNoteSummary:
    def test_text_note(self):
        note = _make_text_note()
        result = _format_note_summary(note)
        assert "Test Note" in result
        assert "notes/note_1" in result
        assert "Type: note" in result

    def test_list_note(self):
        note = _make_list_note()
        result = _format_note_summary(note)
        assert "Shopping" in result
        assert "Type: list" in result

    def test_untitled(self):
        note = _make_text_note(title="")
        result = _format_note_summary(note)
        assert "(untitled)" in result

    def test_trashed(self):
        note = _make_text_note(trashed=True)
        result = _format_note_summary(note)
        assert "Trashed: yes" in result


class TestFormatNoteDetail:
    def test_text_note(self):
        note = _make_text_note()
        result = _format_note_detail(note)
        assert "Test Note" in result
        assert "Hello world" in result
        assert "Type: note" in result

    def test_list_note_with_items(self):
        items = [
            _make_list_item("Milk"),
            _make_list_item("Eggs"),
            _make_list_item("Bread", checked=True),
        ]
        note = _make_list_note(items=items)
        result = _format_note_detail(note)
        assert "Shopping" in result
        assert "Type: list" in result
        assert "[ ] Milk" in result
        assert "[ ] Eggs" in result
        assert "[x] Bread" in result

    def test_with_permissions(self):
        perms = [{"email": "friend@example.com", "role": "WRITER"}]
        note = _make_text_note(permissions=perms)
        result = _format_note_detail(note)
        assert "friend@example.com" in result
        assert "WRITER" in result


# ============================================================
# Tool implementation tests
# ============================================================


class TestListKeepNotes:
    @pytest.mark.asyncio
    async def test_empty(self):
        service = _make_mock_service(list_response={"notes": []})
        result = await _list_keep_notes_impl(service)
        assert "No notes found" in result

    @pytest.mark.asyncio
    async def test_no_notes_key(self):
        service = _make_mock_service(list_response={})
        result = await _list_keep_notes_impl(service)
        assert "No notes found" in result

    @pytest.mark.asyncio
    async def test_returns_notes(self):
        notes = [
            _make_text_note(),
            _make_text_note(name="notes/note_2", title="Note 2"),
        ]
        service = _make_mock_service(list_response={"notes": notes})
        result = await _list_keep_notes_impl(service)
        assert "2 note(s)" in result
        assert "Test Note" in result
        assert "Note 2" in result

    @pytest.mark.asyncio
    async def test_with_filter(self):
        service = _make_mock_service(list_response={"notes": [_make_text_note()]})
        result = await _list_keep_notes_impl(service, filter_str='role = "OWNER"')
        assert "1 note(s)" in result
        service.notes.return_value.list.assert_called_once_with(
            filter='role = "OWNER"', pageSize=100
        )

    @pytest.mark.asyncio
    async def test_pagination(self):
        response = {
            "notes": [_make_text_note()],
            "nextPageToken": "token_abc",
        }
        service = _make_mock_service(list_response=response)
        result = await _list_keep_notes_impl(service)
        assert "Next page token: token_abc" in result

    @pytest.mark.asyncio
    async def test_page_size(self):
        service = _make_mock_service(list_response={"notes": [_make_text_note()]})
        await _list_keep_notes_impl(service, page_size=50)
        service.notes.return_value.list.assert_called_once_with(pageSize=50)

    @pytest.mark.asyncio
    async def test_page_token(self):
        service = _make_mock_service(list_response={"notes": [_make_text_note()]})
        await _list_keep_notes_impl(service, page_token="tok_123")
        service.notes.return_value.list.assert_called_once_with(
            pageSize=100, pageToken="tok_123"
        )


class TestGetKeepNote:
    @pytest.mark.asyncio
    async def test_found(self):
        note = _make_text_note(title="My Note", text="Content here")
        service = _make_mock_service(get_response=note)
        result = await _get_keep_note_impl(service, "notes/note_1")
        assert "My Note" in result
        assert "Content here" in result
        service.notes.return_value.get.assert_called_once_with(name="notes/note_1")

    @pytest.mark.asyncio
    async def test_list_note(self):
        items = [_make_list_item("Milk"), _make_list_item("Bread", checked=True)]
        note = _make_list_note(items=items)
        service = _make_mock_service(get_response=note)
        result = await _get_keep_note_impl(service, "notes/list_1")
        assert "Shopping" in result
        assert "[ ] Milk" in result
        assert "[x] Bread" in result


class TestCreateKeepNote:
    @pytest.mark.asyncio
    async def test_basic(self):
        created = {"name": "notes/new_1", "title": "New Note"}
        service = _make_mock_service(create_response=created)
        result = await _create_keep_note_impl(service, "New Note", "Some text")
        assert "created" in result.lower()
        assert "New Note" in result
        assert "notes/new_1" in result

        service.notes.return_value.create.assert_called_once_with(
            body={
                "title": "New Note",
                "body": {"text": {"text": "Some text"}},
            }
        )

    @pytest.mark.asyncio
    async def test_empty_text(self):
        created = {"name": "notes/new_2", "title": "Empty"}
        service = _make_mock_service(create_response=created)
        result = await _create_keep_note_impl(service, "Empty")
        assert "created" in result.lower()
        service.notes.return_value.create.assert_called_once_with(
            body={
                "title": "Empty",
                "body": {"text": {"text": ""}},
            }
        )


class TestCreateKeepList:
    @pytest.mark.asyncio
    async def test_basic(self):
        created = {"name": "notes/new_list_1", "title": "Shopping"}
        service = _make_mock_service(create_response=created)
        result = await _create_keep_list_impl(service, "Shopping", "Milk\nEggs\nBread")
        assert "created" in result.lower()
        assert "Shopping" in result
        assert "3" in result

        call_args = service.notes.return_value.create.call_args
        body = call_args.kwargs["body"]
        assert body["title"] == "Shopping"
        assert len(body["body"]["list"]["listItems"]) == 3
        assert body["body"]["list"]["listItems"][0]["text"]["text"] == "Milk"
        assert body["body"]["list"]["listItems"][1]["text"]["text"] == "Eggs"
        assert body["body"]["list"]["listItems"][2]["text"]["text"] == "Bread"

    @pytest.mark.asyncio
    async def test_strips_empty_lines(self):
        created = {"name": "notes/new_list_2", "title": "List"}
        service = _make_mock_service(create_response=created)
        result = await _create_keep_list_impl(service, "List", "Item1\n\nItem2\n  \n")
        assert "2" in result

        call_args = service.notes.return_value.create.call_args
        items = call_args.kwargs["body"]["body"]["list"]["listItems"]
        assert len(items) == 2


class TestDeleteKeepNote:
    @pytest.mark.asyncio
    async def test_delete(self):
        service = _make_mock_service()
        result = await _delete_keep_note_impl(service, "notes/note_1")
        assert "deleted" in result.lower()
        assert "notes/note_1" in result
        service.notes.return_value.delete.assert_called_once_with(name="notes/note_1")


class TestShareKeepNote:
    @pytest.mark.asyncio
    async def test_share_success(self):
        perm_response = {
            "permissions": [
                {"email": "friend@example.com", "role": "WRITER"}
            ]
        }
        service = _make_mock_service(permissions_response=perm_response)
        result = await _share_keep_note_impl(
            service, "notes/note_1", "friend@example.com"
        )
        assert "shared" in result.lower()
        assert "friend@example.com" in result
        assert "WRITER" in result

    @pytest.mark.asyncio
    async def test_share_with_role(self):
        perm_response = {
            "permissions": [
                {"email": "viewer@example.com", "role": "READER"}
            ]
        }
        service = _make_mock_service(permissions_response=perm_response)
        result = await _share_keep_note_impl(
            service, "notes/note_1", "viewer@example.com", role="READER"
        )
        assert "shared" in result.lower()
        assert "READER" in result

    @pytest.mark.asyncio
    async def test_share_failure(self):
        service = _make_mock_service(permissions_response={"permissions": []})
        result = await _share_keep_note_impl(
            service, "notes/note_1", "nobody@example.com"
        )
        assert "Failed" in result

    @pytest.mark.asyncio
    async def test_share_api_call(self):
        perm_response = {"permissions": [{"email": "a@b.com", "role": "WRITER"}]}
        service = _make_mock_service(permissions_response=perm_response)
        await _share_keep_note_impl(service, "notes/n1", "a@b.com", "WRITER")

        service.notes.return_value.permissions.return_value.batchCreate.assert_called_once_with(
            parent="notes/n1",
            body={
                "requests": [
                    {
                        "parent": "notes/n1",
                        "permission": {
                            "email": "a@b.com",
                            "role": "WRITER",
                        },
                    }
                ]
            },
        )
