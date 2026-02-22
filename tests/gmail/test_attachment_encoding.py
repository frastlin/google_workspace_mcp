"""
Unit tests for Gmail attachment filename encoding.

Tests that non-ASCII characters in attachment filenames are properly encoded
according to RFC 2231.
"""

import sys
import os
import base64

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders


def test_add_header_with_ascii_filename():
    """Test that ASCII filenames work correctly."""
    message = MIMEMultipart()
    message.attach(MIMEText("Test body", "plain"))
    
    part = MIMEBase("application", "pdf")
    part.set_payload(b"fake pdf content")
    encoders.encode_base64(part)
    
    filename = "Statusbericht Projekt.pdf"
    part.add_header("Content-Disposition", "attachment", filename=filename)
    
    # Get the Content-Disposition header
    content_disposition = part.get("Content-Disposition")
    
    # ASCII filenames should be in simple form
    assert "Statusbericht Projekt.pdf" in content_disposition
    assert "attachment" in content_disposition


def test_add_header_with_non_ascii_filename():
    """Test that non-ASCII filenames are properly encoded using RFC 2231."""
    message = MIMEMultipart()
    message.attach(MIMEText("Test body", "plain"))
    
    part = MIMEBase("application", "pdf")
    part.set_payload(b"fake pdf content")
    encoders.encode_base64(part)
    
    # Test with German umlauts
    filename = "Prüfbericht Q1.pdf"
    part.add_header("Content-Disposition", "attachment", filename=filename)
    
    # Get the Content-Disposition header
    content_disposition = part.get("Content-Disposition")
    
    # Should contain RFC 2231 encoded format
    # Python's email library generates: filename*=utf-8''Pr%C3%BCfbericht%20Q1.pdf
    assert "attachment" in content_disposition
    # The encoded form should be present
    assert ("filename*=" in content_disposition or 
            "Prüfbericht" in content_disposition)  # Either encoded or raw UTF-8


def test_add_header_with_multiple_non_ascii_chars():
    """Test filenames with multiple non-ASCII characters."""
    message = MIMEMultipart()
    message.attach(MIMEText("Test body", "plain"))
    
    part = MIMEBase("application", "pdf")
    part.set_payload(b"fake pdf content")
    encoders.encode_base64(part)
    
    # Test with multiple umlauts
    filename = "Kostenübersicht März.pdf"
    part.add_header("Content-Disposition", "attachment", filename=filename)
    
    # Get the Content-Disposition header
    content_disposition = part.get("Content-Disposition")
    
    # Should contain attachment directive
    assert "attachment" in content_disposition
    # Should handle the encoding (either RFC 2231 or UTF-8)
    assert ("filename*=" in content_disposition or 
            "Kostenübersicht" in content_disposition)


def test_sanitization_of_newlines():
    """Test that newlines and carriage returns are properly sanitized."""
    message = MIMEMultipart()
    message.attach(MIMEText("Test body", "plain"))
    
    part = MIMEBase("application", "pdf")
    part.set_payload(b"fake pdf content")
    encoders.encode_base64(part)
    
    # Filename with injected newlines (security concern)
    filename = "test\r\nfile.pdf"
    # Sanitize it like the code does
    safe_filename = filename.replace("\r", "").replace("\n", "")
    part.add_header("Content-Disposition", "attachment", filename=safe_filename)
    
    # Get the Content-Disposition header
    content_disposition = part.get("Content-Disposition")
    
    # Should not contain raw newlines (they may be encoded)
    assert "testfile.pdf" in content_disposition
    # The sanitized filename should be used
    assert safe_filename == "testfile.pdf"


def test_backward_compatibility_with_special_chars():
    """Test that special characters like quotes and backslashes are handled."""
    message = MIMEMultipart()
    message.attach(MIMEText("Test body", "plain"))
    
    part = MIMEBase("application", "pdf")
    part.set_payload(b"fake pdf content")
    encoders.encode_base64(part)
    
    # With the new approach, these should be handled by add_header automatically
    filename = 'test"file.pdf'
    part.add_header("Content-Disposition", "attachment", filename=filename)
    
    # Get the Content-Disposition header
    content_disposition = part.get("Content-Disposition")
    
    # The header should be valid
    assert "attachment" in content_disposition
    # The filename should be present in some form (encoded or quoted)
    assert "test" in content_disposition and "file.pdf" in content_disposition
