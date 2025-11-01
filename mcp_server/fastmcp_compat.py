"""Compatibility helpers for FastMCP 0.x style APIs.

This module restores the historical ``fastmcp.tool`` decorator interface so that
existing tool implementations can continue to work after upgrading to FastMCP
2.x, where the decorator moved onto the ``FastMCP`` instance.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, List, Set

from fastmcp.tools import FunctionTool
from fastmcp.tools.tool import ToolAnnotations, ToolResultSerializerType
from fastmcp.utilities.types import NotSet, NotSetT


def _normalize_tags(tags: Iterable[str] | None) -> Set[str] | None:
    if tags is None:
        return None
    # FastMCP expects a set; callers historically passed lists/tuples.
    return set(tags)


def tool(
    name_or_fn: str | Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    title: str | None = None,
    description: str | None = None,
    icons: List[dict[str, Any]] | None = None,
    tags: Iterable[str] | None = None,
    annotations: ToolAnnotations | None = None,
    exclude_args: List[str] | None = None,
    output_schema: dict[str, Any] | NotSetT | None = NotSet,
    serializer: ToolResultSerializerType | None = None,
    meta: dict[str, Any] | None = None,
    enabled: bool | None = None,
) -> Callable[[Callable[..., Any]], FunctionTool] | FunctionTool:
    """Backwards-compatible decorator for registering FastMCP tools.

    Supports the original call patterns:
      * ``@tool``
      * ``@tool()``
      * ``@tool(\"name\")``
      * ``@tool(name=\"name\")``
    """

    resolved_name = name

    if isinstance(name_or_fn, str):
        if name is not None:
            raise ValueError(
                "Duplicate tool name supplied; use @tool('name') or @tool(name='name'), not both."
            )
        resolved_name = name_or_fn
        name_or_fn = None
    elif name_or_fn is not None and not callable(name_or_fn):
        raise TypeError(
            "First argument to @tool must be a callable or string name; "
            f"got {type(name_or_fn)!r}."
        )

    def decorator(fn: Callable[..., Any]) -> FunctionTool:
        return FunctionTool.from_function(
            fn=fn,
            name=resolved_name,
            title=title,
            description=description,
            icons=icons,
            tags=_normalize_tags(tags),
            annotations=annotations,
            exclude_args=exclude_args,
            output_schema=output_schema,
            serializer=serializer,
            meta=meta,
            enabled=enabled,
        )

    if name_or_fn is None:
        return decorator

    return decorator(name_or_fn)


__all__ = ["tool"]
