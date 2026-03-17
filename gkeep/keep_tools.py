"""
Google Keep MCP Tools

Provides 6 MCP tools for interacting with Google Keep via the official
Keep API (keep.googleapis.com v1) using standard OAuth2 authentication.
"""

import asyncio
import json
import logging
from typing import Optional

from googleapiclient.errors import HttpError  # type: ignore

from auth.service_decorator import require_google_service
from core.server import server
from core.utils import handle_http_errors

logger = logging.getLogger(__name__)


# --- Note formatting helpers ---


def _format_note_summary(note: dict) -> str:
    """Format a note dict from the Keep API as a brief summary line."""
    name = note.get("name", "")
    title = note.get("title") or "(untitled)"
    body = note.get("body", {})

    if "list" in body:
        kind = "list"
    else:
        kind = "note"

    parts = [f"- {title} (ID: {name})"]
    parts.append(f"  Type: {kind}")

    if note.get("trashed"):
        parts.append("  Trashed: yes")
    if note.get("createTime"):
        parts.append(f"  Created: {note['createTime']}")
    if note.get("updateTime"):
        parts.append(f"  Updated: {note['updateTime']}")

    return "\n".join(parts)


def _format_note_detail(note: dict) -> str:
    """Format a note dict with full content."""
    name = note.get("name", "")
    title = note.get("title") or "(untitled)"
    body = note.get("body", {})

    is_list = "list" in body

    parts = [f"Title: {title}"]
    parts.append(f"ID: {name}")
    parts.append(f"Type: {'list' if is_list else 'note'}")
    parts.append(f"Trashed: {'yes' if note.get('trashed') else 'no'}")

    if note.get("createTime"):
        parts.append(f"Created: {note['createTime']}")
    if note.get("updateTime"):
        parts.append(f"Updated: {note['updateTime']}")

    if is_list:
        list_content = body["list"]
        items = list_content.get("listItems", [])
        unchecked = [i for i in items if not i.get("checked", False)]
        checked = [i for i in items if i.get("checked", False)]
        if unchecked:
            parts.append("\nUnchecked items:")
            for item in unchecked:
                text = item.get("text", {}).get("text", "")
                parts.append(f"  [ ] {text}")
        if checked:
            parts.append("\nChecked items:")
            for item in checked:
                text = item.get("text", {}).get("text", "")
                parts.append(f"  [x] {text}")
    else:
        text_content = body.get("text", {}).get("text", "")
        if text_content:
            parts.append(f"\nContent:\n{text_content}")

    # Show permissions if present
    permissions = note.get("permissions", [])
    if permissions:
        parts.append("\nShared with:")
        for perm in permissions:
            email = perm.get("email", "unknown")
            role = perm.get("role", "unknown")
            parts.append(f"  - {email} ({role})")

    return "\n".join(parts)


# ============================================================
# Tool implementation functions (called directly by tests)
# ============================================================


async def _list_keep_notes_impl(
    service,
    filter_str: Optional[str] = None,
    page_size: int = 100,
    page_token: Optional[str] = None,
) -> str:
    """List notes via the Keep API."""
    kwargs = {}
    if filter_str:
        kwargs["filter"] = filter_str
    if page_size:
        kwargs["pageSize"] = page_size
    if page_token:
        kwargs["pageToken"] = page_token

    response = await asyncio.to_thread(
        service.notes().list(**kwargs).execute
    )

    notes = response.get("notes", [])
    if not notes:
        return "No notes found."

    lines = [f"Found {len(notes)} note(s):\n"]
    for note in notes:
        lines.append(_format_note_summary(note))

    next_page = response.get("nextPageToken")
    if next_page:
        lines.append(f"\nNext page token: {next_page}")

    return "\n".join(lines)


async def _get_keep_note_impl(service, note_name: str) -> str:
    """Get a single note by name."""
    note = await asyncio.to_thread(
        service.notes().get(name=note_name).execute
    )
    return _format_note_detail(note)


async def _create_keep_note_impl(
    service,
    title: str,
    text: str = "",
) -> str:
    """Create a new text note."""
    body = {
        "title": title,
        "body": {
            "text": {
                "text": text,
            }
        },
    }

    note = await asyncio.to_thread(
        service.notes().create(body=body).execute
    )

    return (
        f"Note created successfully.\n"
        f"Title: {note.get('title', '')}\n"
        f"ID: {note.get('name', '')}"
    )


async def _create_keep_list_impl(
    service,
    title: str,
    items: str,
) -> str:
    """Create a new checklist note."""
    list_items = []
    for item_text in items.split("\n"):
        item_text = item_text.strip()
        if item_text:
            list_items.append({
                "text": {"text": item_text},
                "checked": False,
            })

    body = {
        "title": title,
        "body": {
            "list": {
                "listItems": list_items,
            }
        },
    }

    note = await asyncio.to_thread(
        service.notes().create(body=body).execute
    )

    return (
        f"List created successfully.\n"
        f"Title: {note.get('title', '')}\n"
        f"ID: {note.get('name', '')}\n"
        f"Items: {len(list_items)}"
    )


async def _delete_keep_note_impl(service, note_name: str) -> str:
    """Delete a note."""
    await asyncio.to_thread(
        service.notes().delete(name=note_name).execute
    )
    return f"Note {note_name} deleted."


async def _share_keep_note_impl(
    service,
    note_name: str,
    email: str,
    role: str = "WRITER",
) -> str:
    """Share a note with another user."""
    body = {
        "requests": [
            {
                "parent": note_name,
                "permission": {
                    "email": email,
                    "role": role,
                },
            }
        ]
    }

    response = await asyncio.to_thread(
        service.notes().permissions().batchCreate(
            parent=note_name, body=body
        ).execute
    )

    created = response.get("permissions", [])
    if created:
        return f"Note {note_name} shared with {email} as {role}."
    return f"Failed to share note {note_name} with {email}."


# ============================================================
# MCP Tool wrappers
# ============================================================


@server.tool()  # type: ignore
@require_google_service("keep", "keep_read")  # type: ignore
@handle_http_errors("list_keep_notes", service_type="keep")  # type: ignore
async def list_keep_notes(
    service,
    user_google_email: str,
    filter: Optional[str] = None,
    page_size: int = 100,
    page_token: Optional[str] = None,
) -> str:
    """
    List Google Keep notes.

    Returns a summary of notes in the user's Google Keep account.

    Args:
        user_google_email (str): The user's Google email address. Required.
        filter (Optional[str]): Optional filter string for the API (e.g., 'role = "OWNER"').
        page_size (int): Maximum number of notes to return per page. Default: 100.
        page_token (Optional[str]): Token for fetching the next page of results.

    Returns:
        str: Formatted list of notes with titles, IDs, and metadata.
    """
    return await _list_keep_notes_impl(service, filter, page_size, page_token)


@server.tool()  # type: ignore
@require_google_service("keep", "keep_read")  # type: ignore
@handle_http_errors("get_keep_note", service_type="keep")  # type: ignore
async def get_keep_note(
    service,
    user_google_email: str,
    note_name: str,
) -> str:
    """
    Get a single Google Keep note by ID with full content.

    Args:
        user_google_email (str): The user's Google email address. Required.
        note_name (str): The resource name of the note (e.g., 'notes/abc123').

    Returns:
        str: Full note details including title, content, checklist items, and sharing info.
    """
    return await _get_keep_note_impl(service, note_name)


@server.tool()  # type: ignore
@require_google_service("keep", "keep")  # type: ignore
@handle_http_errors("create_keep_note", service_type="keep")  # type: ignore
async def create_keep_note(
    service,
    user_google_email: str,
    title: str,
    text: str = "",
) -> str:
    """
    Create a new Google Keep text note.

    Args:
        user_google_email (str): The user's Google email address. Required.
        title (str): The title of the note.
        text (str): The text content of the note. Default: empty.

    Returns:
        str: Confirmation with the new note's title and ID.
    """
    return await _create_keep_note_impl(service, title, text)


@server.tool()  # type: ignore
@require_google_service("keep", "keep")  # type: ignore
@handle_http_errors("create_keep_list", service_type="keep")  # type: ignore
async def create_keep_list(
    service,
    user_google_email: str,
    title: str,
    items: str,
) -> str:
    """
    Create a new Google Keep checklist.

    Args:
        user_google_email (str): The user's Google email address. Required.
        title (str): The title of the list.
        items (str): Newline-separated list items.

    Returns:
        str: Confirmation with the new list's title, ID, and item count.
    """
    return await _create_keep_list_impl(service, title, items)


@server.tool()  # type: ignore
@require_google_service("keep", "keep")  # type: ignore
@handle_http_errors("delete_keep_note", service_type="keep")  # type: ignore
async def delete_keep_note(
    service,
    user_google_email: str,
    note_name: str,
) -> str:
    """
    Delete a Google Keep note.

    Args:
        user_google_email (str): The user's Google email address. Required.
        note_name (str): The resource name of the note to delete (e.g., 'notes/abc123').

    Returns:
        str: Confirmation message.
    """
    return await _delete_keep_note_impl(service, note_name)


@server.tool()  # type: ignore
@require_google_service("keep", "keep")  # type: ignore
@handle_http_errors("share_keep_note", service_type="keep")  # type: ignore
async def share_keep_note(
    service,
    user_google_email: str,
    note_name: str,
    email: str,
    role: str = "WRITER",
) -> str:
    """
    Share a Google Keep note with another user.

    Args:
        user_google_email (str): The user's Google email address. Required.
        note_name (str): The resource name of the note (e.g., 'notes/abc123').
        email (str): The email address to share with.
        role (str): Permission role: 'WRITER' (default) or 'READER'.

    Returns:
        str: Confirmation message.
    """
    return await _share_keep_note_impl(service, note_name, email, role)
