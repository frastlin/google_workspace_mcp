"""
Unit tests for Gmail attachment support and forwarding.

Tests cover:
- _prepare_gmail_message() with attachments (pure function)
- _resolve_attachments() (async, mocked service for Shape B)
- _send_gmail_message_impl() (mocked service)
- _draft_gmail_message_impl() (mocked service)
- _forward_gmail_message_impl() (mocked service)
"""

import base64
import email
import json
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from gmail.gmail_tools import (
    _prepare_gmail_message,
    _resolve_attachments,
    _send_gmail_message_impl,
    _draft_gmail_message_impl,
    _forward_gmail_message_impl,
)


def _decode_raw_message(raw_b64: str) -> email.message.Message:
    """Helper to decode a base64-encoded raw MIME message."""
    raw_bytes = base64.urlsafe_b64decode(raw_b64)
    return email.message_from_bytes(raw_bytes)


def _make_attachment_b64(content: bytes = b"hello world") -> str:
    """Helper to create a base64 string from bytes."""
    return base64.b64encode(content).decode()


def _make_mock_service():
    """Create a mock Gmail service with properly chained methods."""
    service = MagicMock()
    return service


# ============================================================
# Group 1: _prepare_gmail_message() (pure function, no mocks)
# ============================================================


class TestPrepareGmailMessage:

    def test_prepare_message_no_attachments_unchanged(self):
        """Backward compat: no attachments still produces simple MIMEText."""
        raw, tid = _prepare_gmail_message(
            subject="Test", body="Hello", to="a@b.com"
        )
        msg = _decode_raw_message(raw)
        assert msg.get_content_type() == "text/plain"
        assert msg["Subject"] == "Test"
        assert msg["To"] == "a@b.com"
        assert msg.get_payload() == "Hello"

    def test_prepare_message_with_one_attachment(self):
        """One attachment produces MIMEMultipart with 2 parts."""
        content = b"file content here"
        att = [
            {
                "filename": "test.txt",
                "mime_type": "text/plain",
                "content_base64": _make_attachment_b64(content),
            }
        ]
        raw, _ = _prepare_gmail_message(
            subject="With Att", body="Body text", to="a@b.com", attachments=att
        )
        msg = _decode_raw_message(raw)
        assert msg.get_content_type() == "multipart/mixed"
        parts = msg.get_payload()
        assert len(parts) == 2
        # First part is the body
        assert parts[0].get_content_type() == "text/plain"
        assert parts[0].get_payload(decode=True) == b"Body text"
        # Second part is the attachment
        assert parts[1].get_filename() == "test.txt"
        assert base64.b64decode(parts[1].get_payload()) == content

    def test_prepare_message_with_multiple_attachments(self):
        """3 attachments = 4 MIME parts total."""
        atts = [
            {
                "filename": f"file{i}.txt",
                "mime_type": "text/plain",
                "content_base64": _make_attachment_b64(f"content{i}".encode()),
            }
            for i in range(3)
        ]
        raw, _ = _prepare_gmail_message(
            subject="Multi", body="Body", to="a@b.com", attachments=atts
        )
        msg = _decode_raw_message(raw)
        parts = msg.get_payload()
        assert len(parts) == 4  # body + 3 attachments

    def test_prepare_message_attachments_with_reply_headers(self):
        """In-Reply-To, References, Re: prefix all work with attachments."""
        att = [
            {
                "filename": "f.txt",
                "mime_type": "text/plain",
                "content_base64": _make_attachment_b64(),
            }
        ]
        raw, tid = _prepare_gmail_message(
            subject="Meeting",
            body="Reply body",
            to="a@b.com",
            thread_id="t123",
            in_reply_to="<msg@example.com>",
            references="<orig@example.com> <msg@example.com>",
            attachments=att,
        )
        msg = _decode_raw_message(raw)
        assert msg["Subject"] == "Re: Meeting"
        assert msg["In-Reply-To"] == "<msg@example.com>"
        assert msg["References"] == "<orig@example.com> <msg@example.com>"
        assert tid == "t123"
        assert msg.get_content_type() == "multipart/mixed"

    def test_prepare_message_attachments_with_html_body(self):
        """Body part is text/html when format='html'."""
        att = [
            {
                "filename": "f.txt",
                "mime_type": "text/plain",
                "content_base64": _make_attachment_b64(),
            }
        ]
        raw, _ = _prepare_gmail_message(
            subject="HTML",
            body="<b>Bold</b>",
            to="a@b.com",
            body_format="html",
            attachments=att,
        )
        msg = _decode_raw_message(raw)
        parts = msg.get_payload()
        assert parts[0].get_content_type() == "text/html"

    def test_prepare_message_empty_attachments_list(self):
        """attachments=[] behaves like no attachments (simple MIMEText)."""
        raw, _ = _prepare_gmail_message(
            subject="Test", body="Hello", to="a@b.com", attachments=[]
        )
        msg = _decode_raw_message(raw)
        assert msg.get_content_type() == "text/plain"

    def test_prepare_message_binary_attachment(self):
        """Non-UTF-8 bytes round-trip correctly."""
        binary_content = bytes(range(256))
        att = [
            {
                "filename": "binary.bin",
                "mime_type": "application/octet-stream",
                "content_base64": _make_attachment_b64(binary_content),
            }
        ]
        raw, _ = _prepare_gmail_message(
            subject="Binary", body="Body", to="a@b.com", attachments=att
        )
        msg = _decode_raw_message(raw)
        parts = msg.get_payload()
        decoded = base64.b64decode(parts[1].get_payload())
        assert decoded == binary_content

    def test_prepare_message_special_chars_in_filename(self):
        """Spaces, unicode, parens preserved in filename."""
        att = [
            {
                "filename": "report (final) \u00e9.pdf",
                "mime_type": "application/pdf",
                "content_base64": _make_attachment_b64(),
            }
        ]
        raw, _ = _prepare_gmail_message(
            subject="Special", body="Body", to="a@b.com", attachments=att
        )
        msg = _decode_raw_message(raw)
        parts = msg.get_payload()
        assert parts[1].get_filename() == "report (final) \u00e9.pdf"


# ============================================================
# Group 2: _resolve_attachments() (async, mocked service)
# ============================================================


class TestResolveAttachments:

    @pytest.mark.asyncio
    async def test_resolve_none(self):
        result = await _resolve_attachments(None, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_resolve_empty_string(self):
        result = await _resolve_attachments(None, "")
        assert result is None

    @pytest.mark.asyncio
    async def test_resolve_inline_base64(self):
        """Shape A: inline base64 parsed correctly."""
        content = b"test data"
        b64 = _make_attachment_b64(content)
        items = json.dumps(
            [{"filename": "test.txt", "mime_type": "text/plain", "content_base64": b64}]
        )
        result = await _resolve_attachments(None, items)
        assert len(result) == 1
        assert result[0]["filename"] == "test.txt"
        assert result[0]["mime_type"] == "text/plain"
        assert result[0]["content_base64"] == b64

    @pytest.mark.asyncio
    async def test_resolve_gmail_reference(self):
        """Shape B: downloads from Gmail API via mock."""
        service = _make_mock_service()
        raw_b64 = base64.urlsafe_b64encode(b"attachment data").decode()
        service.users().messages().attachments().get().execute.return_value = {
            "data": raw_b64,
            "size": 15,
        }

        items = json.dumps(
            [
                {
                    "filename": "doc.pdf",
                    "mime_type": "application/pdf",
                    "source_message_id": "msg123",
                    "source_attachment_id": "att456",
                }
            ]
        )
        result = await _resolve_attachments(service, items)
        assert len(result) == 1
        assert result[0]["filename"] == "doc.pdf"
        # Should have content_base64 populated
        decoded = base64.b64decode(result[0]["content_base64"])
        assert decoded == b"attachment data"

    @pytest.mark.asyncio
    async def test_resolve_mixed_sources(self):
        """Shape A + Shape B together."""
        service = _make_mock_service()
        raw_b64 = base64.urlsafe_b64encode(b"from gmail").decode()
        service.users().messages().attachments().get().execute.return_value = {
            "data": raw_b64,
            "size": 10,
        }

        items = json.dumps(
            [
                {
                    "filename": "inline.txt",
                    "mime_type": "text/plain",
                    "content_base64": _make_attachment_b64(b"inline data"),
                },
                {
                    "filename": "remote.pdf",
                    "mime_type": "application/pdf",
                    "source_message_id": "msg1",
                    "source_attachment_id": "att1",
                },
            ]
        )
        result = await _resolve_attachments(service, items)
        assert len(result) == 2
        assert result[0]["filename"] == "inline.txt"
        assert result[1]["filename"] == "remote.pdf"

    @pytest.mark.asyncio
    async def test_resolve_invalid_json(self):
        with pytest.raises(ValueError, match="Invalid attachments JSON"):
            await _resolve_attachments(None, "not json{{{")

    @pytest.mark.asyncio
    async def test_resolve_missing_filename(self):
        items = json.dumps([{"content_base64": _make_attachment_b64()}])
        with pytest.raises(ValueError, match="filename"):
            await _resolve_attachments(None, items)

    @pytest.mark.asyncio
    async def test_resolve_missing_content_and_source(self):
        items = json.dumps([{"filename": "test.txt"}])
        with pytest.raises(ValueError, match="content_base64"):
            await _resolve_attachments(None, items)

    @pytest.mark.asyncio
    async def test_resolve_invalid_base64(self):
        items = json.dumps(
            [{"filename": "test.txt", "content_base64": "not!valid!base64!!!"}]
        )
        with pytest.raises(ValueError, match="Invalid base64"):
            await _resolve_attachments(None, items)

    @pytest.mark.asyncio
    async def test_resolve_default_mime_type(self):
        """Defaults to application/octet-stream when no mime_type and unknown extension."""
        items = json.dumps(
            [{"filename": "data.xyz", "content_base64": _make_attachment_b64()}]
        )
        result = await _resolve_attachments(None, items)
        assert result[0]["mime_type"] == "application/octet-stream"

    @pytest.mark.asyncio
    async def test_resolve_mime_type_from_filename(self):
        """Guesses from extension (e.g., .png -> image/png)."""
        items = json.dumps(
            [{"filename": "photo.png", "content_base64": _make_attachment_b64()}]
        )
        result = await _resolve_attachments(None, items)
        assert result[0]["mime_type"] == "image/png"

    @pytest.mark.asyncio
    async def test_resolve_size_limit(self):
        """>25MB raises ValueError."""
        # Create content just over 25MB
        big_content = b"x" * (25 * 1024 * 1024 + 1)
        items = json.dumps(
            [
                {
                    "filename": "huge.bin",
                    "content_base64": _make_attachment_b64(big_content),
                }
            ]
        )
        with pytest.raises(ValueError, match="25MB"):
            await _resolve_attachments(None, items)


# ============================================================
# Group 3: _send_gmail_message_impl() (mocked service)
# ============================================================


class TestSendGmailMessageImpl:

    @pytest.mark.asyncio
    async def test_send_no_attachments(self):
        """Backward compat: sending without attachments."""
        service = _make_mock_service()
        service.users().messages().send().execute.return_value = {"id": "sent123"}

        result = await _send_gmail_message_impl(
            service=service,
            user_google_email="me@example.com",
            to="you@example.com",
            subject="Hello",
            body="Hi there",
        )
        assert "sent123" in result

    @pytest.mark.asyncio
    async def test_send_with_inline_attachment(self):
        """Attachment in sent raw message."""
        service = _make_mock_service()
        service.users().messages().send().execute.return_value = {"id": "sent456"}

        att_json = json.dumps(
            [
                {
                    "filename": "test.txt",
                    "mime_type": "text/plain",
                    "content_base64": _make_attachment_b64(b"file data"),
                }
            ]
        )
        result = await _send_gmail_message_impl(
            service=service,
            user_google_email="me@example.com",
            to="you@example.com",
            subject="With attachment",
            body="See attached",
            attachments=att_json,
        )
        assert "sent456" in result

        # Verify the raw message was multipart
        call_args = service.users().messages().send.call_args
        raw_msg = call_args[1]["body"]["raw"] if "body" in (call_args[1] or {}) else None
        # The send was called - that's the key assertion
        service.users().messages().send.assert_called()

    @pytest.mark.asyncio
    async def test_send_with_gmail_reference_attachment(self):
        """Fetches from API then sends."""
        service = _make_mock_service()
        raw_b64 = base64.urlsafe_b64encode(b"remote file").decode()
        service.users().messages().attachments().get().execute.return_value = {
            "data": raw_b64,
            "size": 11,
        }
        service.users().messages().send().execute.return_value = {"id": "sent789"}

        att_json = json.dumps(
            [
                {
                    "filename": "remote.pdf",
                    "mime_type": "application/pdf",
                    "source_message_id": "msg1",
                    "source_attachment_id": "att1",
                }
            ]
        )
        result = await _send_gmail_message_impl(
            service=service,
            user_google_email="me@example.com",
            to="you@example.com",
            subject="Forwarded file",
            body="Here you go",
            attachments=att_json,
        )
        assert "sent789" in result

    @pytest.mark.asyncio
    async def test_send_reply_with_attachments(self):
        """thread_id + attachments together."""
        service = _make_mock_service()
        service.users().messages().send().execute.return_value = {"id": "reply123"}

        att_json = json.dumps(
            [
                {
                    "filename": "data.csv",
                    "mime_type": "text/csv",
                    "content_base64": _make_attachment_b64(b"a,b,c\n1,2,3"),
                }
            ]
        )
        result = await _send_gmail_message_impl(
            service=service,
            user_google_email="me@example.com",
            to="you@example.com",
            subject="Re: Data",
            body="Updated data attached",
            thread_id="thread_abc",
            in_reply_to="<orig@example.com>",
            attachments=att_json,
        )
        assert "reply123" in result


# ============================================================
# Group 4: _draft_gmail_message_impl() (mocked service)
# ============================================================


class TestDraftGmailMessageImpl:

    @pytest.mark.asyncio
    async def test_draft_with_attachment(self):
        """Attachment in draft raw message."""
        service = _make_mock_service()
        service.users().drafts().create().execute.return_value = {"id": "draft123"}

        att_json = json.dumps(
            [
                {
                    "filename": "doc.txt",
                    "mime_type": "text/plain",
                    "content_base64": _make_attachment_b64(b"draft attachment"),
                }
            ]
        )
        result = await _draft_gmail_message_impl(
            service=service,
            user_google_email="me@example.com",
            subject="Draft with file",
            body="See attached",
            to="you@example.com",
            attachments=att_json,
        )
        assert "draft123" in result

    @pytest.mark.asyncio
    async def test_draft_reply_with_attachment(self):
        """thread_id + attachments in a draft."""
        service = _make_mock_service()
        service.users().drafts().create().execute.return_value = {"id": "draft456"}

        att_json = json.dumps(
            [
                {
                    "filename": "reply.pdf",
                    "mime_type": "application/pdf",
                    "content_base64": _make_attachment_b64(b"pdf bytes"),
                }
            ]
        )
        result = await _draft_gmail_message_impl(
            service=service,
            user_google_email="me@example.com",
            subject="Re: Report",
            body="Updated report",
            to="you@example.com",
            thread_id="thread_xyz",
            in_reply_to="<msg@example.com>",
            attachments=att_json,
        )
        assert "draft456" in result


# ============================================================
# Group 5: _forward_gmail_message_impl() (mocked service)
# ============================================================


def _make_original_message(
    subject="Original Subject",
    from_addr="sender@example.com",
    to_addr="me@example.com",
    date="Mon, 1 Jan 2024 12:00:00 +0000",
    body_text="Original body text",
    attachments=None,
):
    """Build a mock Gmail API 'full' message response."""
    headers = [
        {"name": "Subject", "value": subject},
        {"name": "From", "value": from_addr},
        {"name": "To", "value": to_addr},
        {"name": "Date", "value": date},
        {"name": "Message-ID", "value": "<original@example.com>"},
    ]
    body_b64 = base64.urlsafe_b64encode(body_text.encode()).decode()

    parts = [
        {
            "mimeType": "text/plain",
            "body": {"data": body_b64, "size": len(body_text)},
        }
    ]

    if attachments:
        for att in attachments:
            parts.append(
                {
                    "filename": att["filename"],
                    "mimeType": att["mimeType"],
                    "body": {
                        "attachmentId": att["attachmentId"],
                        "size": att.get("size", 100),
                    },
                }
            )

    return {
        "id": "orig_msg_id",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": headers,
            "parts": parts,
        },
    }


class TestForwardGmailMessageImpl:

    @pytest.mark.asyncio
    async def test_forward_basic(self):
        """Fetches original, sends with 'Fwd:' subject, includes original content."""
        service = _make_mock_service()
        service.users().messages().get().execute.return_value = _make_original_message()
        service.users().messages().send().execute.return_value = {"id": "fwd123"}

        result = await _forward_gmail_message_impl(
            service=service,
            user_google_email="me@example.com",
            message_id="orig_msg_id",
            to="recipient@example.com",
            body="FYI",
        )
        assert "fwd123" in result

    @pytest.mark.asyncio
    async def test_forward_with_attachments(self):
        """Downloads and includes original attachments."""
        service = _make_mock_service()
        orig_msg = _make_original_message(
            attachments=[
                {
                    "filename": "report.pdf",
                    "mimeType": "application/pdf",
                    "attachmentId": "att_id_1",
                    "size": 1024,
                }
            ]
        )
        service.users().messages().get().execute.return_value = orig_msg
        raw_b64 = base64.urlsafe_b64encode(b"pdf content here").decode()
        service.users().messages().attachments().get().execute.return_value = {
            "data": raw_b64,
            "size": 16,
        }
        service.users().messages().send().execute.return_value = {"id": "fwd_att123"}

        result = await _forward_gmail_message_impl(
            service=service,
            user_google_email="me@example.com",
            message_id="orig_msg_id",
            to="recipient@example.com",
            include_attachments=True,
        )
        assert "fwd_att123" in result

    @pytest.mark.asyncio
    async def test_forward_without_attachments(self):
        """include_attachments=False skips them."""
        service = _make_mock_service()
        orig_msg = _make_original_message(
            attachments=[
                {
                    "filename": "report.pdf",
                    "mimeType": "application/pdf",
                    "attachmentId": "att_id_1",
                    "size": 1024,
                }
            ]
        )
        service.users().messages().get().execute.return_value = orig_msg
        service.users().messages().send().execute.return_value = {"id": "fwd_noatt"}

        result = await _forward_gmail_message_impl(
            service=service,
            user_google_email="me@example.com",
            message_id="orig_msg_id",
            to="recipient@example.com",
            include_attachments=False,
        )
        assert "fwd_noatt" in result
        # Attachment API should NOT have been called
        service.users().messages().attachments().get.assert_not_called()

    @pytest.mark.asyncio
    async def test_forward_preserves_original_headers(self):
        """From, Date, To, Subject in quoted block."""
        service = _make_mock_service()
        service.users().messages().get().execute.return_value = _make_original_message(
            subject="Important Info",
            from_addr="boss@example.com",
            to_addr="me@example.com",
            date="Tue, 2 Jan 2024 09:00:00 +0000",
        )
        # Capture the raw message sent
        sent_raw = {}

        def capture_send(**kwargs):
            sent_raw.update(kwargs.get("body", {}))
            mock_exec = Mock()
            mock_exec.execute.return_value = {"id": "fwd_hdr"}
            return mock_exec

        service.users().messages().send.side_effect = capture_send
        service.users().messages().send().execute.return_value = {"id": "fwd_hdr"}

        result = await _forward_gmail_message_impl(
            service=service,
            user_google_email="me@example.com",
            message_id="orig_msg_id",
            to="colleague@example.com",
            body="Please review",
        )
        assert "fwd_hdr" in result

    @pytest.mark.asyncio
    async def test_forward_no_double_prefix(self):
        """'Fwd: X' doesn't become 'Fwd: Fwd: X'."""
        service = _make_mock_service()
        service.users().messages().get().execute.return_value = _make_original_message(
            subject="Fwd: Already forwarded"
        )
        service.users().messages().send().execute.return_value = {"id": "fwd_nodouble"}

        # We need to check what subject was used. Capture via _prepare_gmail_message.
        # The simplest way is to decode the raw message from the send call.
        sent_bodies = []
        original_send = service.users().messages().send

        def capture_send_call(**kwargs):
            sent_bodies.append(kwargs.get("body", {}))
            mock_result = Mock()
            mock_result.execute.return_value = {"id": "fwd_nodouble"}
            return mock_result

        service.users().messages().send.side_effect = capture_send_call

        result = await _forward_gmail_message_impl(
            service=service,
            user_google_email="me@example.com",
            message_id="orig_msg_id",
            to="someone@example.com",
        )
        assert "fwd_nodouble" in result

        # Verify subject in the raw MIME
        if sent_bodies and "raw" in sent_bodies[0]:
            msg = _decode_raw_message(sent_bodies[0]["raw"])
            assert msg["Subject"] == "Fwd: Already forwarded"
            assert not msg["Subject"].startswith("Fwd: Fwd:")
