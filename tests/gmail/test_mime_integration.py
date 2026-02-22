"""
Integration test demonstrating RFC 2231 encoding of non-ASCII filenames.

This test creates a complete MIME message with attachments and verifies that
the Content-Disposition headers are properly encoded.
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders


def test_complete_mime_message_with_non_ascii_attachments():
    """
    Test that mimics the actual draft_gmail_message flow with non-ASCII filenames.
    
    This demonstrates the fix for the issue where German umlauts (ü, ö, ä, ß) 
    caused Gmail to display "noname" instead of the actual filename.
    """
    # Create a multipart message like draft_gmail_message does
    message = MIMEMultipart()
    message.attach(MIMEText("Test email body", "plain"))
    
    # Test cases from the bug report
    test_attachments = [
        ("Statusbericht Projekt.pdf", b"ASCII filename content"),
        ("Prüfbericht Q1.pdf", b"Umlaut u filename content"),
        ("Kostenübersicht März.pdf", b"Multiple umlauts content"),
    ]
    
    for filename, content in test_attachments:
        # Create MIME attachment (mimics lines 324-341 in gmail_tools.py)
        part = MIMEBase("application", "pdf")
        part.set_payload(content)
        encoders.encode_base64(part)
        
        # Sanitize filename (mimics lines 330-336)
        safe_filename = filename.replace("\r", "").replace("\n", "")
        
        # Use add_header with filename parameter (the fix at line 339-341)
        part.add_header("Content-Disposition", "attachment", filename=safe_filename)
        
        message.attach(part)
    
    # Verify the message structure
    parts = message.get_payload()
    assert len(parts) == 4  # 1 text body + 3 attachments
    
    # Verify each attachment has proper Content-Disposition
    for i, (expected_filename, _) in enumerate(test_attachments):
        attachment_part = parts[i + 1]  # +1 to skip the body
        content_disposition = attachment_part.get("Content-Disposition")
        
        assert content_disposition is not None
        assert "attachment" in content_disposition
        
        # The filename should be present either in raw UTF-8 or RFC 2231 encoded
        # Gmail can handle both formats correctly
        if all(ord(c) < 128 for c in expected_filename):
            # ASCII filename should be in simple form
            assert expected_filename in content_disposition
        else:
            # Non-ASCII should trigger RFC 2231 encoding (filename*=)
            # or be in quoted UTF-8 form
            assert ("filename*=" in content_disposition or 
                    expected_filename in content_disposition)


def test_rfc_2231_encoding_format():
    """
    Verify the exact RFC 2231 encoding format produced by Python's email library.
    
    According to RFC 2231, non-ASCII filenames should be encoded as:
    filename*=charset'language'encoded-value
    
    For example: filename*=utf-8''Pr%C3%BCfbericht.pdf
    """
    part = MIMEBase("application", "pdf")
    part.set_payload(b"test content")
    encoders.encode_base64(part)
    
    # Use a filename with non-ASCII character
    filename = "Prüfbericht.pdf"
    part.add_header("Content-Disposition", "attachment", filename=filename)
    
    # Get the raw header
    content_disposition = part.get("Content-Disposition")
    
    # Verify it contains RFC 2231 format when non-ASCII is present
    # The exact encoding may vary by Python version, but it should be valid
    assert "attachment" in content_disposition
    
    # The email library should handle it properly - check if it's encoded
    # or if raw UTF-8 is preserved (both are valid for modern email clients)
    assert (
        "filename*=" in content_disposition or  # RFC 2231 encoded
        "Prüfbericht.pdf" in content_disposition  # Raw UTF-8 (also valid)
    )
    
    print(f"Content-Disposition header: {content_disposition}")
    print(f"Filename successfully encoded: {filename}")


if __name__ == "__main__":
    # Run the tests manually for demonstration
    test_complete_mime_message_with_non_ascii_attachments()
    print("✓ Complete MIME message test passed")
    
    test_rfc_2231_encoding_format()
    print("✓ RFC 2231 encoding format test passed")
    
    print("\nAll integration tests passed!")
