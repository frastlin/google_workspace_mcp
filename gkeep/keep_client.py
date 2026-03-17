"""
Google Keep client singleton using gkeepapi.

Authentication uses a master token (generated via gpsoauth from an App Password).
The token is stored in the credentials directory alongside other Google service credentials.
"""

import asyncio
import json
import logging
import os
from typing import Optional

import gkeepapi  # type: ignore

logger = logging.getLogger(__name__)

_keep_instance: Optional[gkeepapi.Keep] = None
_keep_authenticated = False

KEEP_TOKEN_FILENAME = "keep_master_token.json"

SETUP_GUIDE = (
    "Google Keep is not configured. To set up:\n\n"
    "1. Enable 2-Step Verification at https://myaccount.google.com/security\n"
    "2. Generate an App Password at https://myaccount.google.com/apppasswords\n"
    "   - Select \"Mail\" (or any app), click Generate, copy the 16-char password\n"
    "3. Paste your app password here and I'll set up Keep for you\n"
    "   - This will authenticate and save your credentials automatically\n"
    "   - You only need to do this once"
)


def _get_credentials_dir() -> str:
    """Get the credentials directory using the same logic as credential_store.py."""
    workspace_creds_dir = os.getenv("WORKSPACE_MCP_CREDENTIALS_DIR")
    google_creds_dir = os.getenv("GOOGLE_MCP_CREDENTIALS_DIR")

    if workspace_creds_dir:
        return os.path.expanduser(workspace_creds_dir)
    elif google_creds_dir:
        return os.path.expanduser(google_creds_dir)
    else:
        return os.path.join(
            os.path.expanduser("~"), ".google_workspace_mcp", "credentials"
        )


def _get_keep_email() -> Optional[str]:
    """Get the email for Keep authentication."""
    return os.getenv("GOOGLE_KEEP_EMAIL") or os.getenv("USER_GOOGLE_EMAIL")


def _get_token_path() -> str:
    """Get the path to the master token file."""
    return os.path.join(_get_credentials_dir(), KEEP_TOKEN_FILENAME)


def _load_master_token() -> Optional[str]:
    """Load the master token from file or environment variable."""
    # Check env var first
    env_token = os.getenv("GOOGLE_KEEP_MASTER_TOKEN")
    if env_token:
        logger.info("Using Keep master token from GOOGLE_KEEP_MASTER_TOKEN env var")
        return env_token

    # Check credentials dir
    token_path = _get_token_path()
    if os.path.exists(token_path):
        try:
            with open(token_path) as f:
                data = json.load(f)
            token = data.get("master_token")
            if token:
                logger.info("Loaded Keep master token from %s", token_path)
                return token
        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.warning("Failed to load Keep master token from %s: %s", token_path, e)

    return None


def save_master_token(master_token: str, email: str) -> str:
    """Save the master token to the credentials directory.

    Returns the path where the token was saved.
    """
    creds_dir = _get_credentials_dir()
    os.makedirs(creds_dir, exist_ok=True)
    token_path = os.path.join(creds_dir, KEEP_TOKEN_FILENAME)

    with open(token_path, "w") as f:
        json.dump({"master_token": master_token, "email": email}, f)

    logger.info("Saved Keep master token to %s", token_path)
    return token_path


async def get_keep_client() -> gkeepapi.Keep:
    """Get the authenticated Keep client singleton.

    Returns the Keep client if authenticated, or raises an exception with
    the setup guide if credentials are missing.
    """
    global _keep_instance, _keep_authenticated

    if _keep_instance is not None and _keep_authenticated:
        return _keep_instance

    email = _get_keep_email()
    if not email:
        raise KeepAuthError(
            "No email configured. Set USER_GOOGLE_EMAIL or GOOGLE_KEEP_EMAIL.\n\n"
            + SETUP_GUIDE
        )

    master_token = _load_master_token()
    if not master_token:
        raise KeepAuthError(SETUP_GUIDE)

    keep = gkeepapi.Keep()
    try:
        success = await asyncio.to_thread(keep.resume, email, master_token)
        if not success:
            raise KeepAuthError(
                "Failed to authenticate with Keep. Token may be expired.\n\n"
                + SETUP_GUIDE
            )
    except Exception as e:
        if "KeepAuthError" in type(e).__name__:
            raise
        raise KeepAuthError(
            f"Failed to authenticate with Keep: {e}\n\n" + SETUP_GUIDE
        ) from e

    await asyncio.to_thread(keep.sync)

    _keep_instance = keep
    _keep_authenticated = True
    logger.info("Keep client authenticated for %s", email)
    return keep


async def login_and_save(email: str, app_password: str) -> str:
    """Login with app password, save the master token, and return success message."""
    global _keep_instance, _keep_authenticated

    keep = gkeepapi.Keep()
    await asyncio.to_thread(keep.login, email, app_password)

    master_token = keep.getMasterToken()
    token_path = save_master_token(master_token, email)

    await asyncio.to_thread(keep.sync)

    _keep_instance = keep
    _keep_authenticated = True
    logger.info("Keep login successful for %s, token saved to %s", email, token_path)

    return (
        f"Keep authentication successful for {email}.\n"
        f"Master token saved to {token_path}.\n"
        "You can now use all Keep tools."
    )


def reset_client():
    """Reset the client singleton (for testing)."""
    global _keep_instance, _keep_authenticated
    _keep_instance = None
    _keep_authenticated = False


class KeepAuthError(Exception):
    """Raised when Keep authentication fails or is not configured."""

    pass
