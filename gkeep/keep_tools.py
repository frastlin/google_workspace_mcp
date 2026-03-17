"""
Google Keep MCP Tools

Provides 12 MCP tools for interacting with Google Keep via gkeepapi.
"""

import asyncio
import logging
from typing import Optional

import gkeepapi  # type: ignore
from gkeepapi.node import ColorValue  # type: ignore

from core.server import server
from gkeep.keep_client import (
    KeepAuthError,
    _get_keep_email,
    login_and_save,
)
from gkeep.keep_decorator import handle_keep_errors, require_keep_service

logger = logging.getLogger(__name__)

# --- Color mapping ---

_COLOR_MAP = {
    "white": ColorValue.White,
    "red": ColorValue.Red,
    "orange": ColorValue.Orange,
    "yellow": ColorValue.Yellow,
    "green": ColorValue.Green,
    "teal": ColorValue.Teal,
    "blue": ColorValue.Blue,
    "cerulean": ColorValue.DarkBlue,
    "purple": ColorValue.Purple,
    "pink": ColorValue.Pink,
    "brown": ColorValue.Brown,
    "gray": ColorValue.Gray,
    "grey": ColorValue.Gray,
}

_REVERSE_COLOR_MAP = {v: k for k, v in _COLOR_MAP.items() if k != "grey"}


def _parse_color(color_str: Optional[str]) -> Optional[ColorValue]:
    """Parse a color string to a ColorValue, or None if invalid/empty."""
    if not color_str:
        return None
    return _COLOR_MAP.get(color_str.lower().strip())


def _color_name(color: Optional[ColorValue]) -> str:
    """Get the display name for a ColorValue."""
    if color is None:
        return "white"
    return _REVERSE_COLOR_MAP.get(color, "white")


# --- Note formatting helpers ---


def _format_note_summary(note) -> str:
    """Format a note as a brief summary line."""
    kind = "list" if hasattr(note, "items") and callable(getattr(note, "items", None)) is False else "note"
    # gkeepapi List objects are instances of gkeepapi.node.List
    try:
        items = note.items if hasattr(note, "unchecked") else None
    except Exception:
        items = None

    if isinstance(note, gkeepapi.node.List):
        kind = "list"
    else:
        kind = "note"

    parts = [f"- {note.title or '(untitled)'} (ID: {note.id})"]
    parts.append(f"  Type: {kind}")

    if note.pinned:
        parts.append("  Pinned: yes")
    if note.color:
        parts.append(f"  Color: {_color_name(note.color)}")
    if note.labels:
        label_names = [l.name for l in note.labels.all()]
        if label_names:
            parts.append(f"  Labels: {', '.join(label_names)}")
    if note.timestamps and hasattr(note.timestamps, "updated"):
        parts.append(f"  Updated: {note.timestamps.updated}")

    return "\n".join(parts)


def _format_note_detail(note) -> str:
    """Format a note with full content."""
    parts = [f"Title: {note.title or '(untitled)'}"]
    parts.append(f"ID: {note.id}")
    parts.append(f"Type: {'list' if isinstance(note, gkeepapi.node.List) else 'note'}")
    parts.append(f"Pinned: {'yes' if note.pinned else 'no'}")
    parts.append(f"Archived: {'yes' if note.archived else 'no'}")
    parts.append(f"Trashed: {'yes' if note.trashed else 'no'}")
    parts.append(f"Color: {_color_name(note.color)}")

    if note.labels:
        label_names = [l.name for l in note.labels.all()]
        if label_names:
            parts.append(f"Labels: {', '.join(label_names)}")

    if note.timestamps:
        if hasattr(note.timestamps, "created"):
            parts.append(f"Created: {note.timestamps.created}")
        if hasattr(note.timestamps, "updated"):
            parts.append(f"Updated: {note.timestamps.updated}")

    if isinstance(note, gkeepapi.node.List):
        unchecked = note.unchecked
        checked = note.checked
        if unchecked:
            parts.append("\nUnchecked items:")
            for item in unchecked:
                parts.append(f"  [ ] {item.text}")
        if checked:
            parts.append("\nChecked items:")
            for item in checked:
                parts.append(f"  [x] {item.text}")
    else:
        if note.text:
            parts.append(f"\nContent:\n{note.text}")

    return "\n".join(parts)


# ============================================================
# Tool implementation functions (called directly by tests)
# ============================================================


async def _setup_keep_auth_impl(app_password: str) -> str:
    """Authenticate with Google Keep using an App Password and save the master token."""
    email = _get_keep_email()
    if not email:
        return (
            "No email configured. Set USER_GOOGLE_EMAIL or GOOGLE_KEEP_EMAIL "
            "environment variable before running setup."
        )

    try:
        return await login_and_save(email, app_password)
    except Exception as e:
        return f"Keep authentication failed: {e}"


async def _list_keep_notes_impl(
    keep: gkeepapi.Keep,
    pinned: Optional[bool] = None,
    archived: bool = False,
    labels: Optional[str] = None,
    color: Optional[str] = None,
    query: Optional[str] = None,
) -> str:
    """List notes with optional filtering."""
    notes = keep.all()

    results = []
    for note in notes:
        # Skip trashed notes
        if note.trashed:
            continue

        # Archived filter
        if not archived and note.archived:
            continue
        if archived and not note.archived:
            continue

        # Pinned filter
        if pinned is not None and note.pinned != pinned:
            continue

        # Color filter
        if color:
            target_color = _parse_color(color)
            if target_color is not None and note.color != target_color:
                continue

        # Label filter
        if labels:
            note_labels = [l.name.lower() for l in note.labels.all()]
            if labels.lower() not in note_labels:
                continue

        # Query filter (search in title and text)
        if query:
            q = query.lower()
            title_match = note.title and q in note.title.lower()
            text_match = hasattr(note, "text") and note.text and q in note.text.lower()
            if not title_match and not text_match:
                continue

        results.append(note)

    if not results:
        return "No notes found matching the specified filters."

    lines = [f"Found {len(results)} note(s):\n"]
    for note in results:
        lines.append(_format_note_summary(note))
    return "\n".join(lines)


async def _get_keep_note_impl(keep: gkeepapi.Keep, note_id: str) -> str:
    """Get a single note by ID with full content."""
    note = keep.get(note_id)
    if not note:
        return f"Note not found: {note_id}"
    return _format_note_detail(note)


async def _create_keep_note_impl(
    keep: gkeepapi.Keep,
    title: str,
    text: str = "",
    color: Optional[str] = None,
    pinned: bool = False,
    labels: Optional[str] = None,
) -> str:
    """Create a new text note."""
    note = keep.createNote(title, text)

    if color:
        parsed = _parse_color(color)
        if parsed:
            note.color = parsed

    if pinned:
        note.pinned = True

    if labels:
        for label_name in [l.strip() for l in labels.split(",")]:
            label = _find_or_create_label(keep, label_name)
            note.labels.add(label)

    await asyncio.to_thread(keep.sync)

    return (
        f"Note created successfully.\n"
        f"Title: {note.title}\n"
        f"ID: {note.id}"
    )


async def _create_keep_list_impl(
    keep: gkeepapi.Keep,
    title: str,
    items: str,
    color: Optional[str] = None,
    pinned: bool = False,
    labels: Optional[str] = None,
) -> str:
    """Create a new checklist note."""
    item_list = [
        (item.strip(), False)
        for item in items.split("\n")
        if item.strip()
    ]

    note = keep.createList(title, item_list)

    if color:
        parsed = _parse_color(color)
        if parsed:
            note.color = parsed

    if pinned:
        note.pinned = True

    if labels:
        for label_name in [l.strip() for l in labels.split(",")]:
            label = _find_or_create_label(keep, label_name)
            note.labels.add(label)

    await asyncio.to_thread(keep.sync)

    return (
        f"List created successfully.\n"
        f"Title: {note.title}\n"
        f"ID: {note.id}\n"
        f"Items: {len(item_list)}"
    )


async def _update_keep_note_impl(
    keep: gkeepapi.Keep,
    note_id: str,
    title: Optional[str] = None,
    text: Optional[str] = None,
    color: Optional[str] = None,
    pinned: Optional[bool] = None,
    archived: Optional[bool] = None,
) -> str:
    """Update an existing note's properties."""
    note = keep.get(note_id)
    if not note:
        return f"Note not found: {note_id}"

    changes = []
    if title is not None:
        note.title = title
        changes.append("title")
    if text is not None and not isinstance(note, gkeepapi.node.List):
        note.text = text
        changes.append("text")
    if color is not None:
        parsed = _parse_color(color)
        if parsed:
            note.color = parsed
            changes.append("color")
    if pinned is not None:
        note.pinned = pinned
        changes.append("pinned")
    if archived is not None:
        note.archived = archived
        changes.append("archived")

    if not changes:
        return "No changes specified."

    await asyncio.to_thread(keep.sync)

    return f"Note {note_id} updated: {', '.join(changes)}."


async def _delete_keep_note_impl(keep: gkeepapi.Keep, note_id: str) -> str:
    """Trash a note."""
    note = keep.get(note_id)
    if not note:
        return f"Note not found: {note_id}"

    note.trash()
    await asyncio.to_thread(keep.sync)

    return f"Note {note_id} moved to trash."


async def _search_keep_notes_impl(
    keep: gkeepapi.Keep,
    query: Optional[str] = None,
    labels: Optional[str] = None,
    color: Optional[str] = None,
    pinned: Optional[bool] = None,
    archived: bool = False,
    trashed: bool = False,
) -> str:
    """Advanced search across notes with multiple filters."""
    notes = keep.all()

    results = []
    for note in notes:
        # Trashed filter
        if not trashed and note.trashed:
            continue
        if trashed and not note.trashed:
            continue

        # Archived filter
        if not archived and note.archived:
            continue

        # Pinned filter
        if pinned is not None and note.pinned != pinned:
            continue

        # Color filter
        if color:
            target_color = _parse_color(color)
            if target_color is not None and note.color != target_color:
                continue

        # Label filter
        if labels:
            note_labels = [l.name.lower() for l in note.labels.all()]
            if labels.lower() not in note_labels:
                continue

        # Query filter
        if query:
            q = query.lower()
            title_match = note.title and q in note.title.lower()
            text_match = hasattr(note, "text") and note.text and q in note.text.lower()
            if not title_match and not text_match:
                continue

        results.append(note)

    if not results:
        return "No notes found matching the specified filters."

    lines = [f"Found {len(results)} note(s):\n"]
    for note in results:
        lines.append(_format_note_summary(note))
    return "\n".join(lines)


async def _manage_keep_labels_impl(
    keep: gkeepapi.Keep,
    action: str,
    label_name: Optional[str] = None,
) -> str:
    """Create, list, or delete labels."""
    action = action.lower().strip()

    if action == "list":
        labels = keep.labels()
        if not labels:
            return "No labels found."
        lines = ["Labels:"]
        for label in labels:
            lines.append(f"- {label.name} (ID: {label.id})")
        return "\n".join(lines)

    if not label_name:
        return "label_name is required for create and delete actions."

    if action == "create":
        existing = keep.findLabel(label_name)
        if existing:
            return f"Label '{label_name}' already exists (ID: {existing.id})."
        label = keep.createLabel(label_name)
        await asyncio.to_thread(keep.sync)
        return f"Label '{label_name}' created (ID: {label.id})."

    if action == "delete":
        label = keep.findLabel(label_name)
        if not label:
            return f"Label '{label_name}' not found."
        keep.deleteLabel(label.id)
        await asyncio.to_thread(keep.sync)
        return f"Label '{label_name}' deleted."

    return f"Unknown action: {action}. Use 'list', 'create', or 'delete'."


async def _manage_keep_note_labels_impl(
    keep: gkeepapi.Keep,
    note_id: str,
    action: str,
    label_name: str,
) -> str:
    """Add or remove labels on a note."""
    note = keep.get(note_id)
    if not note:
        return f"Note not found: {note_id}"

    action = action.lower().strip()

    if action == "add":
        label = _find_or_create_label(keep, label_name)
        note.labels.add(label)
        await asyncio.to_thread(keep.sync)
        return f"Label '{label_name}' added to note {note_id}."

    if action == "remove":
        label = keep.findLabel(label_name)
        if not label:
            return f"Label '{label_name}' not found."
        note.labels.remove(label)
        await asyncio.to_thread(keep.sync)
        return f"Label '{label_name}' removed from note {note_id}."

    return f"Unknown action: {action}. Use 'add' or 'remove'."


async def _manage_keep_list_items_impl(
    keep: gkeepapi.Keep,
    note_id: str,
    action: str,
    text: Optional[str] = None,
    item_index: Optional[int] = None,
) -> str:
    """Add, remove, check, or uncheck list items."""
    note = keep.get(note_id)
    if not note:
        return f"Note not found: {note_id}"

    if not isinstance(note, gkeepapi.node.List):
        return f"Note {note_id} is not a list."

    action = action.lower().strip()

    if action == "add":
        if not text:
            return "text is required for add action."
        note.add(text, False)
        await asyncio.to_thread(keep.sync)
        return f"Item '{text}' added to list {note_id}."

    # For check/uncheck/remove, we need to find the item
    all_items = list(note.unchecked) + list(note.checked)

    if item_index is not None:
        if item_index < 0 or item_index >= len(all_items):
            return f"Item index {item_index} is out of range (0-{len(all_items) - 1})."
        item = all_items[item_index]
    elif text:
        # Find by text match
        item = None
        for i in all_items:
            if i.text.lower() == text.lower():
                item = i
                break
        if not item:
            return f"Item '{text}' not found in list."
    else:
        return "Either text or item_index is required."

    if action == "check":
        item.checked = True
        await asyncio.to_thread(keep.sync)
        return f"Item '{item.text}' checked in list {note_id}."

    if action == "uncheck":
        item.checked = False
        await asyncio.to_thread(keep.sync)
        return f"Item '{item.text}' unchecked in list {note_id}."

    if action == "remove":
        item.delete()
        await asyncio.to_thread(keep.sync)
        return f"Item '{item.text}' removed from list {note_id}."

    return f"Unknown action: {action}. Use 'add', 'remove', 'check', or 'uncheck'."


async def _undelete_keep_note_impl(keep: gkeepapi.Keep, note_id: str) -> str:
    """Restore a trashed note."""
    note = keep.get(note_id)
    if not note:
        return f"Note not found: {note_id}"

    if not note.trashed:
        return f"Note {note_id} is not in trash."

    note.untrash()
    await asyncio.to_thread(keep.sync)

    return f"Note {note_id} restored from trash."


# --- Helper ---


def _find_or_create_label(keep: gkeepapi.Keep, label_name: str):
    """Find a label by name or create it if it doesn't exist."""
    label = keep.findLabel(label_name)
    if not label:
        label = keep.createLabel(label_name)
    return label


# ============================================================
# MCP Tool wrappers
# ============================================================


@server.tool()  # type: ignore
@handle_keep_errors("setup_keep_auth")  # type: ignore
async def setup_keep_auth(app_password: str) -> str:
    """
    One-time setup: authenticate Google Keep with an App Password.

    Generates and saves a master token so all other Keep tools work automatically.
    You only need to run this once.

    Args:
        app_password (str): A 16-character Google App Password. Generate one at
            https://myaccount.google.com/apppasswords

    Returns:
        str: Success message or error details.
    """
    return await _setup_keep_auth_impl(app_password)


@server.tool()  # type: ignore
@require_keep_service  # type: ignore
@handle_keep_errors("list_keep_notes")  # type: ignore
async def list_keep_notes(
    keep: gkeepapi.Keep,
    pinned: Optional[bool] = None,
    archived: bool = False,
    labels: Optional[str] = None,
    color: Optional[str] = None,
    query: Optional[str] = None,
) -> str:
    """
    List Google Keep notes with optional filtering.

    Args:
        pinned (Optional[bool]): Filter by pinned status. None returns all.
        archived (bool): If True, show only archived notes. Default: False.
        labels (Optional[str]): Filter by label name.
        color (Optional[str]): Filter by color (white, red, orange, yellow, green, teal, blue, cerulean, purple, pink, brown, gray).
        query (Optional[str]): Search text in title and content.

    Returns:
        str: Formatted list of matching notes.
    """
    return await _list_keep_notes_impl(keep, pinned, archived, labels, color, query)


@server.tool()  # type: ignore
@require_keep_service  # type: ignore
@handle_keep_errors("get_keep_note")  # type: ignore
async def get_keep_note(keep: gkeepapi.Keep, note_id: str) -> str:
    """
    Get a single Google Keep note by ID with full content.

    Args:
        note_id (str): The ID of the note to retrieve.

    Returns:
        str: Full note details including title, content, labels, and checklist items.
    """
    return await _get_keep_note_impl(keep, note_id)


@server.tool()  # type: ignore
@require_keep_service  # type: ignore
@handle_keep_errors("create_keep_note")  # type: ignore
async def create_keep_note(
    keep: gkeepapi.Keep,
    title: str,
    text: str = "",
    color: Optional[str] = None,
    pinned: bool = False,
    labels: Optional[str] = None,
) -> str:
    """
    Create a new Google Keep text note.

    Args:
        title (str): The title of the note.
        text (str): The text content of the note. Default: empty.
        color (Optional[str]): Note color (white, red, orange, yellow, green, teal, blue, cerulean, purple, pink, brown, gray).
        pinned (bool): Whether to pin the note. Default: False.
        labels (Optional[str]): Comma-separated label names to apply.

    Returns:
        str: Confirmation with the new note's title and ID.
    """
    return await _create_keep_note_impl(keep, title, text, color, pinned, labels)


@server.tool()  # type: ignore
@require_keep_service  # type: ignore
@handle_keep_errors("create_keep_list")  # type: ignore
async def create_keep_list(
    keep: gkeepapi.Keep,
    title: str,
    items: str,
    color: Optional[str] = None,
    pinned: bool = False,
    labels: Optional[str] = None,
) -> str:
    """
    Create a new Google Keep checklist.

    Args:
        title (str): The title of the list.
        items (str): Newline-separated list items.
        color (Optional[str]): Note color (white, red, orange, yellow, green, teal, blue, cerulean, purple, pink, brown, gray).
        pinned (bool): Whether to pin the note. Default: False.
        labels (Optional[str]): Comma-separated label names to apply.

    Returns:
        str: Confirmation with the new list's title, ID, and item count.
    """
    return await _create_keep_list_impl(keep, title, items, color, pinned, labels)


@server.tool()  # type: ignore
@require_keep_service  # type: ignore
@handle_keep_errors("update_keep_note")  # type: ignore
async def update_keep_note(
    keep: gkeepapi.Keep,
    note_id: str,
    title: Optional[str] = None,
    text: Optional[str] = None,
    color: Optional[str] = None,
    pinned: Optional[bool] = None,
    archived: Optional[bool] = None,
) -> str:
    """
    Update an existing Google Keep note.

    Args:
        note_id (str): The ID of the note to update.
        title (Optional[str]): New title.
        text (Optional[str]): New text content (only for text notes, not lists).
        color (Optional[str]): New color.
        pinned (Optional[bool]): New pinned status.
        archived (Optional[bool]): New archived status.

    Returns:
        str: Confirmation of what was updated.
    """
    return await _update_keep_note_impl(keep, note_id, title, text, color, pinned, archived)


@server.tool()  # type: ignore
@require_keep_service  # type: ignore
@handle_keep_errors("delete_keep_note")  # type: ignore
async def delete_keep_note(keep: gkeepapi.Keep, note_id: str) -> str:
    """
    Move a Google Keep note to trash.

    Args:
        note_id (str): The ID of the note to trash.

    Returns:
        str: Confirmation message.
    """
    return await _delete_keep_note_impl(keep, note_id)


@server.tool()  # type: ignore
@require_keep_service  # type: ignore
@handle_keep_errors("search_keep_notes")  # type: ignore
async def search_keep_notes(
    keep: gkeepapi.Keep,
    query: Optional[str] = None,
    labels: Optional[str] = None,
    color: Optional[str] = None,
    pinned: Optional[bool] = None,
    archived: bool = False,
    trashed: bool = False,
) -> str:
    """
    Advanced search across Google Keep notes with multiple filters.

    Combines query text search with label, color, pin, archive, and trash filters.

    Args:
        query (Optional[str]): Search text in title and content.
        labels (Optional[str]): Filter by label name.
        color (Optional[str]): Filter by color.
        pinned (Optional[bool]): Filter by pinned status.
        archived (bool): Include archived notes. Default: False.
        trashed (bool): Include trashed notes. Default: False.

    Returns:
        str: Formatted list of matching notes.
    """
    return await _search_keep_notes_impl(keep, query, labels, color, pinned, archived, trashed)


@server.tool()  # type: ignore
@require_keep_service  # type: ignore
@handle_keep_errors("manage_keep_labels")  # type: ignore
async def manage_keep_labels(
    keep: gkeepapi.Keep,
    action: str,
    label_name: Optional[str] = None,
) -> str:
    """
    Create, list, or delete Google Keep labels.

    Args:
        action (str): Action to perform: 'list', 'create', or 'delete'.
        label_name (Optional[str]): Label name (required for 'create' and 'delete').

    Returns:
        str: Result of the action.
    """
    return await _manage_keep_labels_impl(keep, action, label_name)


@server.tool()  # type: ignore
@require_keep_service  # type: ignore
@handle_keep_errors("manage_keep_note_labels")  # type: ignore
async def manage_keep_note_labels(
    keep: gkeepapi.Keep,
    note_id: str,
    action: str,
    label_name: str,
) -> str:
    """
    Add or remove labels on a Google Keep note.

    Args:
        note_id (str): The ID of the note.
        action (str): Action to perform: 'add' or 'remove'.
        label_name (str): The label name to add or remove.

    Returns:
        str: Confirmation message.
    """
    return await _manage_keep_note_labels_impl(keep, note_id, action, label_name)


@server.tool()  # type: ignore
@require_keep_service  # type: ignore
@handle_keep_errors("manage_keep_list_items")  # type: ignore
async def manage_keep_list_items(
    keep: gkeepapi.Keep,
    note_id: str,
    action: str,
    text: Optional[str] = None,
    item_index: Optional[int] = None,
) -> str:
    """
    Add, remove, check, or uncheck items in a Google Keep checklist.

    Args:
        note_id (str): The ID of the list note.
        action (str): Action to perform: 'add', 'remove', 'check', or 'uncheck'.
        text (Optional[str]): Item text. Required for 'add'. For other actions, used to find item by text match.
        item_index (Optional[int]): Item index (0-based). Alternative to text for finding items.

    Returns:
        str: Confirmation message.
    """
    return await _manage_keep_list_items_impl(keep, note_id, action, text, item_index)


@server.tool()  # type: ignore
@require_keep_service  # type: ignore
@handle_keep_errors("undelete_keep_note")  # type: ignore
async def undelete_keep_note(keep: gkeepapi.Keep, note_id: str) -> str:
    """
    Restore a Google Keep note from trash.

    Args:
        note_id (str): The ID of the trashed note to restore.

    Returns:
        str: Confirmation message.
    """
    return await _undelete_keep_note_impl(keep, note_id)
