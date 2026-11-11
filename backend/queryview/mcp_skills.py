"""The MCP Skills extension (`io.modelcontextprotocol/skills`): serves the
SKILL.md files under `skills/` as `skill://<name>/SKILL.md` resources and
answers `skills/list` / `skills/get`."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml
from mcp.server.extension import Extension, MethodBinding, ResourceBinding
from mcp.server.mcpserver.resources import TextResource
from mcp.shared.exceptions import MCPError
from mcp_types import RequestParams
from mcp_types.jsonrpc import INVALID_PARAMS

SKILLS_DIR = Path(__file__).parent / "skills"
# Skills ship inside the package, so they only change with a new release.
_CACHE = {"resultType": "complete", "ttlMs": 300_000, "cacheScope": "public"}


class GetParams(RequestParams):
    uri: str


def _load(path: Path) -> tuple[str, str, dict[str, Any]]:
    text = path.read_text()
    _, front, _ = text.split("---", 2)
    meta = yaml.safe_load(front)
    assert meta["name"] == path.parent.name, f"{path}: name must match its directory"
    return f"skill://{meta['name']}/SKILL.md", text, meta


class SkillsExtension(Extension):
    identifier = "io.modelcontextprotocol/skills"

    def __init__(self) -> None:
        self._skills = {uri: (text, meta) for uri, text, meta in map(_load, sorted(SKILLS_DIR.glob("*/SKILL.md")))}

    def _entry(self, uri: str) -> dict[str, Any]:
        text, meta = self._skills[uri]
        data = text.encode()
        digest = f"sha256:{hashlib.sha256(data).hexdigest()}"
        return {"uri": uri, "frontmatter": meta, "resources": [{"uri": uri, "digest": digest, "size": len(data)}]}

    def resources(self) -> list[ResourceBinding]:
        return [
            ResourceBinding(
                TextResource(
                    uri=uri, name=meta["name"], description=meta["description"], mime_type="text/markdown", text=text
                )
            )
            for uri, (text, meta) in self._skills.items()
        ]

    def methods(self) -> list[MethodBinding]:
        async def list_skills(ctx: Any, params: RequestParams) -> dict[str, Any]:
            return {"skills": [self._entry(uri) for uri in self._skills], **_CACHE}

        async def get_skill(ctx: Any, params: GetParams) -> dict[str, Any]:
            if params.uri not in self._skills:
                raise MCPError(INVALID_PARAMS, f"unknown skill: {params.uri}")
            return {"skill": self._entry(params.uri), **_CACHE}

        return [
            MethodBinding("skills/list", RequestParams, list_skills),
            MethodBinding("skills/get", GetParams, get_skill),
        ]
