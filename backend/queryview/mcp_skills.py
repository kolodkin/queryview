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
# Skills only change with a release; the SDK stamps resultType per protocol version.
_CACHE = {"ttlMs": 300_000, "cacheScope": "public"}


class GetParams(RequestParams):
    uri: str


def _load(path: Path) -> tuple[str, str, dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"{path}: must start with YAML frontmatter")
    meta = yaml.safe_load(text.split("---", 2)[1])
    if meta.get("name") != path.parent.name or not meta.get("description"):
        raise ValueError(f"{path}: needs a description and a name matching its directory")
    return f"skill://{meta['name']}/SKILL.md", text, meta


def _entry(uri: str, text: str, meta: dict[str, Any]) -> dict[str, Any]:
    data = text.encode()
    digest = f"sha256:{hashlib.sha256(data).hexdigest()}"
    return {"uri": uri, "frontmatter": meta, "resources": [{"uri": uri, "digest": digest, "size": len(data)}]}


class SkillsExtension(Extension):
    identifier = "io.modelcontextprotocol/skills"

    def __init__(self) -> None:
        self._skills = {uri: (text, meta) for uri, text, meta in map(_load, sorted(SKILLS_DIR.glob("*/SKILL.md")))}
        self._entries = {uri: _entry(uri, text, meta) for uri, (text, meta) in self._skills.items()}

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
            return {"skills": list(self._entries.values()), **_CACHE}

        async def get_skill(ctx: Any, params: GetParams) -> dict[str, Any]:
            if params.uri not in self._entries:
                raise MCPError(INVALID_PARAMS, f"unknown skill: {params.uri}")
            return {"skill": self._entries[params.uri], **_CACHE}

        return [
            MethodBinding("skills/list", RequestParams, list_skills),
            MethodBinding("skills/get", GetParams, get_skill),
        ]
