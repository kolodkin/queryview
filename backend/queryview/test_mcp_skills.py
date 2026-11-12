"""The Skills extension, through an in-process MCP client."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

import mcp_types as types
import pytest
from mcp import Client
from mcp.shared.exceptions import MCPError
from mcp_types.jsonrpc import INVALID_PARAMS
from pydantic import TypeAdapter

from queryview.mcp_server import mcp

URI = "skill://queryview/SKILL.md"
_D = TypeAdapter(dict[str, Any])


async def _call(c: Client, method: str, **params: Any) -> dict[str, Any]:
    return await c.session.send_request(types.Request[Any, Any](method=method, params=params), _D)


def test_skill_is_listed_fetched_and_readable():
    async def go():
        async with Client(mcp) as c:
            assert "io.modelcontextprotocol/skills" in c.server_capabilities.extensions
            assert URI in c.session.instructions
            listed = (await _call(c, "skills/list"))["skills"]
            got = (await _call(c, "skills/get", uri=URI))["skill"]
            text = (await c.read_resource(URI)).contents[0].text
            with pytest.raises(MCPError) as e:
                await _call(c, "skills/get", uri="skill://nope/SKILL.md")
        return listed, got, text, e.value.code

    listed, got, text, code = asyncio.run(go())
    assert listed == [got]
    assert got["frontmatter"]["name"] == "queryview"
    # The manifest digest must match the bytes resources/read serves.
    data = text.encode()
    assert got["resources"] == [{"uri": URI, "digest": f"sha256:{hashlib.sha256(data).hexdigest()}", "size": len(data)}]
    assert code == INVALID_PARAMS
