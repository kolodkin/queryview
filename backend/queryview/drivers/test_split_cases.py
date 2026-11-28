"""The server's half of the shared split cases; the page's half is in
frontend/src/app/scriptRun.test.ts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from queryview.drivers.base import split_statements

CASES = json.loads((Path(__file__).parent / "split_cases.json").read_text(encoding="utf-8"))


# req: designs/scripts/same-split
@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_split_statements_matches_the_shared_cases(case):
    assert split_statements(case["script"], case["mysql"]) == case["statements"]
