"""Reusable confirmation helpers for destructive MCP tools."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def requires_confirmation(param_name: str, action_description: str) -> Callable[[F], F]:
    """Mark a tool as requiring an explicit confirmation flag."""

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs)

        setattr(wrapper, "confirmation_param", param_name)
        setattr(wrapper, "action_description", action_description)
        return wrapper  # type: ignore[return-value]

    return decorator
