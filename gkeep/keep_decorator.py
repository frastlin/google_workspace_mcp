"""
Decorators for Google Keep MCP tools.

Provides @require_keep_service (injects Keep client) and @handle_keep_errors
(standardized error handling) that mirror the patterns used by other services.
"""

import inspect
import logging
from functools import wraps

from gkeep.keep_client import KeepAuthError, get_keep_client

logger = logging.getLogger(__name__)


def require_keep_service(func):
    """Decorator that injects an authenticated Keep client as the first argument.

    The decorated function must have 'keep' as its first parameter.
    This parameter is removed from the MCP tool signature so callers don't see it.

    If authentication fails, returns the setup guide instead of raising.
    """
    original_sig = inspect.signature(func)
    params = list(original_sig.parameters.values())

    if not params or params[0].name != "keep":
        raise TypeError(
            f"Function '{func.__name__}' decorated with @require_keep_service "
            "must have 'keep' as its first parameter."
        )

    # Remove 'keep' from the visible MCP tool signature
    wrapper_sig = original_sig.replace(parameters=params[1:])

    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            keep = await get_keep_client()
        except KeepAuthError as e:
            return str(e)

        return await func(keep, *args, **kwargs)

    wrapper.__signature__ = wrapper_sig
    return wrapper


def handle_keep_errors(tool_name: str):
    """Decorator for standardized error handling in Keep tools.

    Catches common exceptions and returns user-friendly error messages.
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except KeepAuthError as e:
                return str(e)
            except Exception as e:
                message = f"Error in {tool_name}: {e}"
                logger.error(message, exc_info=True)
                return message

        # Preserve the signature from any prior decorator
        if hasattr(func, "__signature__"):
            wrapper.__signature__ = func.__signature__

        return wrapper

    return decorator
