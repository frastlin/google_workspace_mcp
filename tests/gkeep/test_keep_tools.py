"""Tests for gkeep.keep_tools module.

Tests call the _impl functions directly to bypass MCP decorators.
"""

from unittest.mock import MagicMock, patch, AsyncMock

import pytest

import gkeepapi.node  # type: ignore

from gkeep.keep_tools import (
    _create_keep_list_impl,
    _create_keep_note_impl,
    _delete_keep_note_impl,
    _get_keep_note_impl,
    _list_keep_notes_impl,
    _manage_keep_labels_impl,
    _manage_keep_list_items_impl,
    _manage_keep_note_labels_impl,
    _search_keep_notes_impl,
    _setup_keep_auth_impl,
    _undelete_keep_note_impl,
    _update_keep_note_impl,
)


# --- Fixtures for mock notes ---


def _make_mock_label(name="Work", label_id="lbl_1"):
    label = MagicMock()
    label.name = name
    label.id = label_id
    return label


def _make_mock_labels_collection(labels=None):
    """Create a mock labels collection that supports .all()."""
    coll = MagicMock()
    coll.all.return_value = labels or []
    return coll


def _make_mock_timestamps(created="2025-01-01T00:00:00Z", updated="2025-01-02T00:00:00Z"):
    ts = MagicMock()
    ts.created = created
    ts.updated = updated
    return ts


def _make_text_note(
    note_id="note_1",
    title="Test Note",
    text="Hello world",
    pinned=False,
    archived=False,
    trashed=False,
    color=None,
    labels=None,
):
    note = MagicMock(spec=gkeepapi.node.Note)
    note.id = note_id
    note.title = title
    note.text = text
    note.pinned = pinned
    note.archived = archived
    note.trashed = trashed
    note.color = color
    note.labels = _make_mock_labels_collection(labels)
    note.timestamps = _make_mock_timestamps()
    # Ensure isinstance check for List fails
    note.__class__ = gkeepapi.node.Note
    return note


def _make_list_note(
    note_id="list_1",
    title="Shopping",
    unchecked=None,
    checked=None,
    pinned=False,
    archived=False,
    trashed=False,
    color=None,
    labels=None,
):
    note = MagicMock(spec=gkeepapi.node.List)
    note.id = note_id
    note.title = title
    note.pinned = pinned
    note.archived = archived
    note.trashed = trashed
    note.color = color
    note.labels = _make_mock_labels_collection(labels)
    note.timestamps = _make_mock_timestamps()
    note.__class__ = gkeepapi.node.List

    # List items
    note.unchecked = unchecked or []
    note.checked = checked or []
    note.add = MagicMock()

    return note


def _make_list_item(text="Milk", checked=False):
    item = MagicMock()
    item.text = text
    item.checked = checked
    item.delete = MagicMock()
    return item


def _make_mock_keep(notes=None, labels=None):
    """Create a mock Keep client."""
    keep = MagicMock()
    keep.all.return_value = notes or []
    keep.sync = MagicMock()

    # get() looks up by ID
    note_map = {n.id: n for n in (notes or [])}
    keep.get.side_effect = lambda nid: note_map.get(nid)

    # Labels
    label_list = labels or []
    keep.labels.return_value = label_list
    label_map = {l.name: l for l in label_list}
    keep.findLabel.side_effect = lambda name: label_map.get(name)

    def _create_label(name):
        lbl = _make_mock_label(name, f"lbl_{name}")
        label_map[name] = lbl
        label_list.append(lbl)
        return lbl

    keep.createLabel.side_effect = _create_label
    keep.deleteLabel = MagicMock()

    # createNote / createList return mock notes
    def _create_note(title, text=""):
        n = _make_text_note(note_id="new_note_1", title=title, text=text)
        return n

    def _create_list(title, items):
        n = _make_list_note(note_id="new_list_1", title=title)
        return n

    keep.createNote.side_effect = _create_note
    keep.createList.side_effect = _create_list

    return keep


# ============================================================
# Tests
# ============================================================


class TestSetupKeepAuth:
    @pytest.mark.asyncio
    async def test_no_email(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_KEEP_EMAIL", raising=False)
        monkeypatch.delenv("USER_GOOGLE_EMAIL", raising=False)
        result = await _setup_keep_auth_impl("fake_password")
        assert "No email configured" in result

    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        monkeypatch.setenv("USER_GOOGLE_EMAIL", "user@test.com")

        with patch("gkeep.keep_tools.login_and_save", new_callable=AsyncMock) as mock_login:
            mock_login.return_value = "Keep authentication successful for user@test.com."
            result = await _setup_keep_auth_impl("myapppassword")

        assert "successful" in result
        mock_login.assert_awaited_once_with("user@test.com", "myapppassword")

    @pytest.mark.asyncio
    async def test_failure(self, monkeypatch):
        monkeypatch.setenv("USER_GOOGLE_EMAIL", "user@test.com")

        with patch("gkeep.keep_tools.login_and_save", new_callable=AsyncMock) as mock_login:
            mock_login.side_effect = Exception("Invalid credentials")
            result = await _setup_keep_auth_impl("badpassword")

        assert "failed" in result.lower()


class TestListKeepNotes:
    @pytest.mark.asyncio
    async def test_empty(self):
        keep = _make_mock_keep()
        result = await _list_keep_notes_impl(keep)
        assert "No notes found" in result

    @pytest.mark.asyncio
    async def test_returns_notes(self):
        notes = [_make_text_note(), _make_text_note(note_id="note_2", title="Note 2")]
        keep = _make_mock_keep(notes)
        result = await _list_keep_notes_impl(keep)
        assert "2 note(s)" in result
        assert "Test Note" in result
        assert "Note 2" in result

    @pytest.mark.asyncio
    async def test_filter_pinned(self):
        notes = [
            _make_text_note(note_id="n1", title="Pinned", pinned=True),
            _make_text_note(note_id="n2", title="Unpinned", pinned=False),
        ]
        keep = _make_mock_keep(notes)
        result = await _list_keep_notes_impl(keep, pinned=True)
        assert "1 note(s)" in result
        assert "Pinned" in result
        assert "Unpinned" not in result

    @pytest.mark.asyncio
    async def test_filter_archived(self):
        notes = [
            _make_text_note(note_id="n1", title="Active"),
            _make_text_note(note_id="n2", title="Archived", archived=True),
        ]
        keep = _make_mock_keep(notes)
        result = await _list_keep_notes_impl(keep, archived=True)
        assert "1 note(s)" in result
        assert "Archived" in result

    @pytest.mark.asyncio
    async def test_skips_trashed(self):
        notes = [
            _make_text_note(note_id="n1", title="Active"),
            _make_text_note(note_id="n2", title="Trashed", trashed=True),
        ]
        keep = _make_mock_keep(notes)
        result = await _list_keep_notes_impl(keep)
        assert "1 note(s)" in result
        assert "Trashed" not in result

    @pytest.mark.asyncio
    async def test_filter_query(self):
        notes = [
            _make_text_note(note_id="n1", title="Groceries", text="buy milk"),
            _make_text_note(note_id="n2", title="Work", text="meeting at 3"),
        ]
        keep = _make_mock_keep(notes)
        result = await _list_keep_notes_impl(keep, query="milk")
        assert "1 note(s)" in result
        assert "Groceries" in result

    @pytest.mark.asyncio
    async def test_filter_label(self):
        label = _make_mock_label("Work")
        notes = [
            _make_text_note(note_id="n1", title="Has label", labels=[label]),
            _make_text_note(note_id="n2", title="No label"),
        ]
        keep = _make_mock_keep(notes)
        result = await _list_keep_notes_impl(keep, labels="Work")
        assert "1 note(s)" in result
        assert "Has label" in result


class TestGetKeepNote:
    @pytest.mark.asyncio
    async def test_found(self):
        note = _make_text_note(title="My Note", text="Content here")
        keep = _make_mock_keep([note])
        result = await _get_keep_note_impl(keep, "note_1")
        assert "My Note" in result
        assert "Content here" in result

    @pytest.mark.asyncio
    async def test_not_found(self):
        keep = _make_mock_keep()
        result = await _get_keep_note_impl(keep, "nonexistent")
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_list_note_shows_items(self):
        items = [_make_list_item("Milk"), _make_list_item("Eggs")]
        checked_items = [_make_list_item("Bread", checked=True)]
        note = _make_list_note(
            note_id="list_1",
            title="Shopping",
            unchecked=items,
            checked=checked_items,
        )
        keep = _make_mock_keep([note])
        result = await _get_keep_note_impl(keep, "list_1")
        assert "Shopping" in result
        assert "[ ] Milk" in result
        assert "[ ] Eggs" in result
        assert "[x] Bread" in result


class TestCreateKeepNote:
    @pytest.mark.asyncio
    async def test_basic(self):
        keep = _make_mock_keep()
        result = await _create_keep_note_impl(keep, "New Note", "Some text")
        assert "created" in result.lower()
        assert "New Note" in result
        keep.createNote.assert_called_once_with("New Note", "Some text")
        keep.sync.assert_called_once()

    @pytest.mark.asyncio
    async def test_with_pin(self):
        keep = _make_mock_keep()
        result = await _create_keep_note_impl(keep, "Pinned", pinned=True)
        assert "created" in result.lower()


class TestCreateKeepList:
    @pytest.mark.asyncio
    async def test_basic(self):
        keep = _make_mock_keep()
        result = await _create_keep_list_impl(keep, "Shopping", "Milk\nEggs\nBread")
        assert "created" in result.lower()
        assert "Shopping" in result
        assert "3" in result  # 3 items
        keep.sync.assert_called_once()


class TestUpdateKeepNote:
    @pytest.mark.asyncio
    async def test_update_title(self):
        note = _make_text_note()
        keep = _make_mock_keep([note])
        result = await _update_keep_note_impl(keep, "note_1", title="New Title")
        assert "updated" in result.lower()
        assert "title" in result
        assert note.title == "New Title"
        keep.sync.assert_called_once()

    @pytest.mark.asyncio
    async def test_not_found(self):
        keep = _make_mock_keep()
        result = await _update_keep_note_impl(keep, "bad_id", title="X")
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_no_changes(self):
        note = _make_text_note()
        keep = _make_mock_keep([note])
        result = await _update_keep_note_impl(keep, "note_1")
        assert "No changes" in result


class TestDeleteKeepNote:
    @pytest.mark.asyncio
    async def test_trash(self):
        note = _make_text_note()
        keep = _make_mock_keep([note])
        result = await _delete_keep_note_impl(keep, "note_1")
        assert "trash" in result.lower()
        note.trash.assert_called_once()
        keep.sync.assert_called_once()

    @pytest.mark.asyncio
    async def test_not_found(self):
        keep = _make_mock_keep()
        result = await _delete_keep_note_impl(keep, "bad_id")
        assert "not found" in result.lower()


class TestSearchKeepNotes:
    @pytest.mark.asyncio
    async def test_combined_filters(self):
        label = _make_mock_label("Work")
        notes = [
            _make_text_note(note_id="n1", title="Work meeting", pinned=True, labels=[label]),
            _make_text_note(note_id="n2", title="Grocery list", pinned=False),
            _make_text_note(note_id="n3", title="Work notes", pinned=True),
        ]
        keep = _make_mock_keep(notes)
        result = await _search_keep_notes_impl(keep, query="work", labels="Work", pinned=True)
        assert "1 note(s)" in result
        assert "Work meeting" in result

    @pytest.mark.asyncio
    async def test_trashed_filter(self):
        notes = [
            _make_text_note(note_id="n1", title="Active"),
            _make_text_note(note_id="n2", title="Trashed", trashed=True),
        ]
        keep = _make_mock_keep(notes)
        result = await _search_keep_notes_impl(keep, trashed=True)
        assert "1 note(s)" in result
        assert "Trashed" in result


class TestManageKeepLabels:
    @pytest.mark.asyncio
    async def test_list_labels(self):
        labels = [_make_mock_label("Work"), _make_mock_label("Personal", "lbl_2")]
        keep = _make_mock_keep(labels=labels)
        result = await _manage_keep_labels_impl(keep, "list")
        assert "Work" in result
        assert "Personal" in result

    @pytest.mark.asyncio
    async def test_list_empty(self):
        keep = _make_mock_keep()
        result = await _manage_keep_labels_impl(keep, "list")
        assert "No labels" in result

    @pytest.mark.asyncio
    async def test_create_label(self):
        keep = _make_mock_keep()
        result = await _manage_keep_labels_impl(keep, "create", "NewLabel")
        assert "created" in result.lower()
        assert "NewLabel" in result

    @pytest.mark.asyncio
    async def test_create_existing(self):
        labels = [_make_mock_label("Existing")]
        keep = _make_mock_keep(labels=labels)
        result = await _manage_keep_labels_impl(keep, "create", "Existing")
        assert "already exists" in result

    @pytest.mark.asyncio
    async def test_delete_label(self):
        labels = [_make_mock_label("ToDelete")]
        keep = _make_mock_keep(labels=labels)
        result = await _manage_keep_labels_impl(keep, "delete", "ToDelete")
        assert "deleted" in result.lower()

    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        keep = _make_mock_keep()
        result = await _manage_keep_labels_impl(keep, "delete", "Ghost")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_missing_label_name(self):
        keep = _make_mock_keep()
        result = await _manage_keep_labels_impl(keep, "create")
        assert "required" in result.lower()


class TestManageKeepNoteLabels:
    @pytest.mark.asyncio
    async def test_add_label(self):
        note = _make_text_note()
        label = _make_mock_label("Work")
        keep = _make_mock_keep([note], [label])
        result = await _manage_keep_note_labels_impl(keep, "note_1", "add", "Work")
        assert "added" in result.lower()

    @pytest.mark.asyncio
    async def test_remove_label(self):
        label = _make_mock_label("Work")
        note = _make_text_note(labels=[label])
        keep = _make_mock_keep([note], [label])
        result = await _manage_keep_note_labels_impl(keep, "note_1", "remove", "Work")
        assert "removed" in result.lower()

    @pytest.mark.asyncio
    async def test_note_not_found(self):
        keep = _make_mock_keep()
        result = await _manage_keep_note_labels_impl(keep, "bad_id", "add", "Work")
        assert "not found" in result.lower()


class TestManageKeepListItems:
    @pytest.mark.asyncio
    async def test_add_item(self):
        note = _make_list_note()
        keep = _make_mock_keep([note])
        result = await _manage_keep_list_items_impl(keep, "list_1", "add", text="Bananas")
        assert "added" in result.lower()
        note.add.assert_called_once_with("Bananas", False)

    @pytest.mark.asyncio
    async def test_check_item_by_text(self):
        item = _make_list_item("Milk")
        note = _make_list_note(unchecked=[item])
        keep = _make_mock_keep([note])
        result = await _manage_keep_list_items_impl(keep, "list_1", "check", text="Milk")
        assert "checked" in result.lower()
        assert item.checked is True

    @pytest.mark.asyncio
    async def test_uncheck_item_by_index(self):
        item = _make_list_item("Bread", checked=True)
        note = _make_list_note(checked=[item])
        keep = _make_mock_keep([note])
        result = await _manage_keep_list_items_impl(keep, "list_1", "uncheck", item_index=0)
        assert "unchecked" in result.lower()
        assert item.checked is False

    @pytest.mark.asyncio
    async def test_remove_item(self):
        item = _make_list_item("Old item")
        note = _make_list_note(unchecked=[item])
        keep = _make_mock_keep([note])
        result = await _manage_keep_list_items_impl(keep, "list_1", "remove", text="Old item")
        assert "removed" in result.lower()
        item.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_not_a_list(self):
        note = _make_text_note()
        keep = _make_mock_keep([note])
        result = await _manage_keep_list_items_impl(keep, "note_1", "add", text="Item")
        assert "not a list" in result.lower()

    @pytest.mark.asyncio
    async def test_item_not_found(self):
        note = _make_list_note(unchecked=[_make_list_item("Existing")])
        keep = _make_mock_keep([note])
        result = await _manage_keep_list_items_impl(keep, "list_1", "check", text="Ghost")
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_index_out_of_range(self):
        note = _make_list_note(unchecked=[_make_list_item("Only")])
        keep = _make_mock_keep([note])
        result = await _manage_keep_list_items_impl(keep, "list_1", "check", item_index=5)
        assert "out of range" in result.lower()

    @pytest.mark.asyncio
    async def test_add_requires_text(self):
        note = _make_list_note()
        keep = _make_mock_keep([note])
        result = await _manage_keep_list_items_impl(keep, "list_1", "add")
        assert "required" in result.lower()


class TestUndeleteKeepNote:
    @pytest.mark.asyncio
    async def test_restore(self):
        note = _make_text_note(trashed=True)
        keep = _make_mock_keep([note])
        result = await _undelete_keep_note_impl(keep, "note_1")
        assert "restored" in result.lower()
        note.untrash.assert_called_once()

    @pytest.mark.asyncio
    async def test_not_trashed(self):
        note = _make_text_note()
        keep = _make_mock_keep([note])
        result = await _undelete_keep_note_impl(keep, "note_1")
        assert "not in trash" in result.lower()

    @pytest.mark.asyncio
    async def test_not_found(self):
        keep = _make_mock_keep()
        result = await _undelete_keep_note_impl(keep, "bad_id")
        assert "not found" in result.lower()
