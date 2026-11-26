"""Tests for vmodel_check: each rule is exercised on a throwaway repo tree."""

from collections.abc import Mapping
from pathlib import Path

from vmodel_check import check, main, parse_ids

PAGE = "<!-- req: system/dash/rerun -->\nA param change re-runs.\n"
SPEC = "// req: system/dash/rerun\ntest('x', () => {})\n"


def repo(tmp_path: Path, files: Mapping[str, str | bytes]) -> Path:
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text if isinstance(text, bytes) else text.encode())
    return tmp_path


def test_parse_ids():
    assert parse_ids("<!-- req: system/a/x, system/a/y -->") == ["system/a/x", "system/a/y"]
    assert parse_ids("  // req: system/a/x") == ["system/a/x"]
    assert parse_ids("# req: architecture/b/z") == ["architecture/b/z"]
    assert parse_ids("# required: nothing") == []


def test_tied_repo_is_clean(tmp_path):
    r = check(repo(tmp_path, {"docs/system/dash.md": PAGE, "e2e/dash.spec.ts": SPEC}))
    assert r.errors == [] and r.matrix["system"] == {"system/dash/rerun": ["e2e/dash.spec.ts"]}


def test_duplicate_id(tmp_path):
    r = check(repo(tmp_path, {"docs/system/dash.md": PAGE + PAGE, "e2e/dash.spec.ts": SPEC}))
    assert any("defined twice" in e for e in r.errors)


def test_unknown_id_in_test(tmp_path):
    r = check(repo(tmp_path, {"e2e/dash.spec.ts": SPEC}))
    assert any("no doc defines" in e for e in r.errors)


def test_prefix_must_match_page(tmp_path):
    r = check(repo(tmp_path, {"docs/system/other.md": PAGE, "e2e/dash.spec.ts": SPEC}))
    assert any("prefix" in e for e in r.errors)


def test_malformed_marker(tmp_path):
    r = check(
        repo(
            tmp_path,
            {"e2e/a.spec.ts": "// req: Dashboard Params\n", "backend/queryview/test_a.py": "# req: dashboard/x\n"},
        )
    )
    assert len(r.errors) == 2


def test_fenced_marker_defines_nothing(tmp_path):
    r = check(repo(tmp_path, {"docs/system/dash.md": f"```\n{PAGE}```\n"}))
    assert r.errors == [] and r.matrix["system"] == {}


def test_non_utf8_file_does_not_crash(tmp_path):
    assert check(repo(tmp_path, {"e2e/bad.spec.ts": b"\xff\xfe"})).errors == []


def test_system_id_needs_a_browser_test(tmp_path):
    r = check(
        repo(
            tmp_path,
            {
                "docs/system/dash.md": PAGE,
                "backend/queryview/dash.py": '"""Doc."""\n',
                "backend/queryview/test_dash.py": "# req: system/dash/rerun\n",
            },
        )
    )
    assert any("no test in e2e/" in e for e in r.errors)


def test_an_acceptance_test_may_also_prove_a_system_id(tmp_path):
    req = "<!-- req: requirements/user/goal -->\nA goal.\n"
    both = "// req: requirements/user/goal, system/dash/rerun\ntest('x', () => {})\n"
    r = check(
        repo(tmp_path, {"docs/requirements/user.md": req, "docs/system/dash.md": PAGE, "e2e/acceptance.spec.ts": both})
    )
    assert r.errors == []
    assert r.matrix["system"] == {"system/dash/rerun": ["e2e/acceptance.spec.ts"]}


def test_a_spec_in_a_subfolder_of_e2e_is_seen(tmp_path):
    r = check(repo(tmp_path, {"docs/system/dash.md": PAGE, "e2e/dash/params.spec.ts": SPEC}))
    assert r.errors == []
    assert r.matrix["system"] == {"system/dash/rerun": ["e2e/dash/params.spec.ts"]}
    r = check(repo(tmp_path, {"e2e/dash/untagged.spec.ts": "test('x', () => {})\n"}))
    assert any("e2e/dash/untagged.spec.ts" in g for g in r.gaps)


def test_layer_proof_locations(tmp_path):
    req = "<!-- req: requirements/user/goal -->\nA goal.\n"
    files = {"docs/requirements/user.md": req, "e2e/dash.spec.ts": "// req: requirements/user/goal\n"}
    assert any("no test in e2e/acceptance.spec.ts" in e for e in check(repo(tmp_path, files)).errors)
    files = {"docs/requirements/user.md": req, "e2e/acceptance.spec.ts": "// req: requirements/user/goal\n"}
    assert check(repo(tmp_path, files)).errors == []
    arch = "<!-- req: architecture/db/pool -->\nA pool.\n"
    files = {"docs/architecture/db.md": arch, "backend/queryview/test_api_db.py": "# req: architecture/db/pool\n"}
    r = check(repo(tmp_path, files))
    assert r.errors == [] and not any("test_api_db" in g for g in r.gaps)
    files = {"docs/architecture/db.md": arch, "frontend/src/core/x.test.ts": "// req: architecture/db/pool\n"}
    assert check(repo(tmp_path, files)).errors == []


def test_unit_file_pairs_by_name(tmp_path):
    r = check(
        repo(tmp_path, {"backend/queryview/test_sessions.py": "", "backend/queryview/sessions.py": '"""Doc."""\n'})
    )
    assert r.errors == [] and r.gaps == []
    r = check(repo(tmp_path, {"backend/queryview/sessions.py": "x = 1\n"}))
    assert any("sessions.py" in e for e in r.errors)
    files = {"frontend/src/core/rows.test.ts": "", "frontend/src/core/rows.tsx": "\n// Rows.\nexport {}\n"}
    assert not any("rows" in e for e in check(repo(tmp_path, files)).errors)
    files = {"frontend/src/core/rows.tsx": "export {}\n"}
    assert any("rows.tsx" in e for e in check(repo(tmp_path, files)).errors)
    r = check(repo(tmp_path, {"backend/queryview/test_api_db.py": ""}))
    assert any("test_api_db.py" in g for g in r.gaps) and not any("test_api_db.py" in e for e in r.errors)


def test_gaps(tmp_path):
    files = {
        "docs/system/empty.md": "text\n",
        "e2e/x.spec.ts": "test('x', () => {})\n",
        "docs/future.md": "<!-- req: system/a/b -->\n",
        "docs/superpowers/specs/x.md": "<!-- req: nope -->\n",
    }
    r = check(repo(tmp_path, files))
    assert r.errors == []
    assert len(r.gaps) == 2 and any("empty.md" in g for g in r.gaps) and any("x.spec.ts" in g for g in r.gaps)


def test_untagged_repo_exits_zero(tmp_path):
    root = repo(tmp_path, {"docs/dashboard.md": "text\n", "e2e/app.spec.ts": "test('x', () => {})\n"})
    assert main(["--root", str(root)]) == 0
    assert main(["--root", str(root), "--strict"]) == 1


def test_an_error_fails_without_strict(tmp_path):
    assert main(["--root", str(repo(tmp_path, {"docs/system/dash.md": "text\n", "e2e/dash.spec.ts": SPEC}))]) == 1


def test_errors_print_after_gaps(tmp_path, capsys):
    root = repo(tmp_path, {"docs/system/empty.md": "text\n", "e2e/dash.spec.ts": SPEC})
    main(["--root", str(root)])
    lines = capsys.readouterr().out.splitlines()
    kinds = [ln.split(":")[0] for ln in lines if ln.startswith(("gap:", "error:"))]
    assert kinds == sorted(kinds, key=lambda k: k == "error") and "gap" in kinds and "error" in kinds


def test_a_root_without_docs_fails_with_one_line(tmp_path, capsys):
    assert main(["--root", str(tmp_path)]) != 0
    out = capsys.readouterr()
    assert out.out == "" and out.err.strip() == f"error: {tmp_path} has no docs/ directory"


def test_test_main_pairs_with_dunder_main(tmp_path):
    files = {"backend/queryview/test_main.py": "", "backend/queryview/__main__.py": '"""Doc."""\n'}
    r = check(repo(tmp_path, files))
    assert r.errors == [] and r.gaps == []


def test_a_decisions_page_needs_no_id(tmp_path):
    assert check(repo(tmp_path, {"docs/architecture/decisions.md": "Why.\n"})).gaps == []
