"""BAROGROOVE's MCP server, mounted on the same FastAPI app as the REST API.

Deliberately import-free. ``main.py`` reaches straight through to
``app.mcp.server.mount_mcp``, and re-exporting it here would only add a second import
path to the same object while making this package's import cost non-zero.

    server.py     the MCP server over streamable HTTP; ``mount_mcp(app)`` is the entry point
    manifest.py   tool models, tool specs, and ``GET /mcp/manifest``; no ``mcp`` dependency
    functions.py  the A2UI ``callAgentFunction`` registry; no ``mcp`` dependency

The file exists so that ``app.mcp`` resolves as a regular package rather than relying on
namespace-package semantics inside a parent that has its own ``__init__.py``.
"""

from __future__ import annotations
