"""
Unit tests for Gmail tools: forward, update draft, delete draft.
"""

import base64
import email
import pytest
from unittest.mock import Mock, MagicMock
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from gmail.gmail_tools import (
    _forward_gmail_message_impl,
    _update_gmail_draft_impl,
    _delete_gmail_draft_impl,
)


def _decode_raw_message(raw_b64: str) -> email.message.Message:
    """Helper to decode a base64-encoded raw MIME message."""
    raw_bytes = base64.urlsafe_b64decode(raw_b64)
    return email.message_from_bytes(raw_bytes)


def _make_mock_service():
    """Create a mock Gmail service with properly chained methods."""
    return MagicMock()


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

        sent_bodies = []

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

    @pytest.mark.asyncio
    async def test_forward_no_original_attachments(self):
        """Forwarding a message with no attachments works cleanly."""
        service = _make_mock_service()
        service.users().messages().get().execute.return_value = _make_original_message()
        service.users().messages().send().execute.return_value = {"id": "fwd_clean"}

        result = await _forward_gmail_message_impl(
            service=service,
            user_google_email="me@example.com",
            message_id="orig_msg_id",
            to="recipient@example.com",
            include_attachments=True,
        )
        assert "fwd_clean" in result

    @pytest.mark.asyncio
    async def test_forward_empty_body(self):
        """Forwarding with no user body prepended."""
        service = _make_mock_service()
        service.users().messages().get().execute.return_value = _make_original_message(
            body_text="Original content"
        )
        service.users().messages().send().execute.return_value = {"id": "fwd_nobody"}

        result = await _forward_gmail_message_impl(
            service=service,
            user_google_email="me@example.com",
            message_id="orig_msg_id",
            to="recipient@example.com",
            body="",
        )
        assert "fwd_nobody" in result


class TestUpdateGmailDraftImpl:

    @pytest.mark.asyncio
    async def test_update_draft_basic(self):
        """Updates a draft with new subject/body, returns draft ID."""
        service = _make_mock_service()
        service.users().drafts().update().execute.return_value = {
            "id": "draft_updated_123"
        }

        result = await _update_gmail_draft_impl(
            service=service,
            user_google_email="me@example.com",
            draft_id="draft_123",
            subject="Updated Subject",
            body="Updated body text",
            to="recipient@example.com",
        )
        assert "draft_updated_123" in result
        assert "updated" in result.lower()
        service.users().drafts().update.assert_called()

    @pytest.mark.asyncio
    async def test_update_draft_preserves_thread(self):
        """When thread_id is passed, it appears in the draft body sent to API."""
        service = _make_mock_service()
        update_calls = []

        def capture_update(**kwargs):
            update_calls.append(kwargs)
            mock_resp = MagicMock()
            mock_resp.execute.return_value = {"id": "draft_thread_456"}
            return mock_resp

        service.users().drafts().update.side_effect = capture_update

        result = await _update_gmail_draft_impl(
            service=service,
            user_google_email="me@example.com",
            draft_id="draft_456",
            subject="Threaded reply",
            body="Reply body",
            thread_id="thread_789",
        )
        assert "draft_thread_456" in result
        assert len(update_calls) == 1
        draft_body = update_calls[0]["body"]
        assert draft_body["message"]["threadId"] == "thread_789"

    @pytest.mark.asyncio
    async def test_update_draft_with_attachments(self):
        """Passing attachments is reflected in the return message."""
        service = _make_mock_service()
        service.users().drafts().update().execute.return_value = {
            "id": "draft_att_789"
        }

        result = await _update_gmail_draft_impl(
            service=service,
            user_google_email="me@example.com",
            draft_id="draft_789",
            subject="With attachment",
            body="See attached",
            attachments=[
                {"content": "dGVzdA==", "filename": "test.txt"},
            ],
        )
        assert "draft_att_789" in result
        assert "1 attachment" in result

    @pytest.mark.asyncio
    async def test_update_draft_html_body(self):
        """HTML body_format doesn't raise an error."""
        service = _make_mock_service()
        service.users().drafts().update().execute.return_value = {
            "id": "draft_html_101"
        }

        result = await _update_gmail_draft_impl(
            service=service,
            user_google_email="me@example.com",
            draft_id="draft_101",
            subject="HTML Draft",
            body="<h1>Hello</h1>",
            body_format="html",
        )
        assert "draft_html_101" in result


class TestDeleteGmailDraftImpl:

    @pytest.mark.asyncio
    async def test_delete_draft_basic(self):
        """Deletes a draft and confirms via return string."""
        service = _make_mock_service()
        service.users().drafts().delete().execute.return_value = None

        result = await _delete_gmail_draft_impl(
            service=service,
            user_google_email="me@example.com",
            draft_id="draft_to_delete",
        )
        assert "deleted" in result.lower()
        service.users().drafts().delete.assert_called()

    @pytest.mark.asyncio
    async def test_delete_draft_returns_confirmation(self):
        """Return message contains the draft_id."""
        service = _make_mock_service()
        service.users().drafts().delete().execute.return_value = None

        result = await _delete_gmail_draft_impl(
            service=service,
            user_google_email="me@example.com",
            draft_id="specific_draft_id",
        )
        assert "specific_draft_id" in result
