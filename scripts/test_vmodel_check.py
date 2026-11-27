"""Tests for vmodel_check: each rule is exercised on a throwaway repo tree."""

from collections.abc import Mapping
from pathlib import Path

from vmodel_check import check, main, parse_ids

PAGE = "<!-- req: rerun -->\nA param change re-runs.\n"
SPEC = "// req: user_guide/dash/rerun\ntest('x', () => {})\n"


def repo(tmp_path: Path, files: Mapping[str, str | bytes]) -> Path:
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text if isinstance(text, bytes) else text.encode())
    return tmp_path


def test_parse_ids():
    assert parse_ids("<!-- req: user_guide/a/x, user_guide/a/y -->") == ["user_guide/a/x", "user_guide/a/y"]
    assert parse_ids("  // req: user_guide/a/x") == ["user_guide/a/x"]
    assert parse_ids("# req: architecture/b/z") == ["architecture/b/z"]
    assert parse_ids("# required: nothing") == []


def test_tied_repo_is_clean(tmp_path):
    r = check(repo(tmp_path, {"docs/user_guide/dash.md": PAGE, "e2e/dash.spec.ts": SPEC}))
    assert r.errors == [] and r.matrix["user_guide"] == {"user_guide/dash/rerun": ["e2e/dash.spec.ts"]}


def test_duplicate_id(tmp_path):
    r = check(repo(tmp_path, {"docs/user_guide/dash.md": PAGE + PAGE, "e2e/dash.spec.ts": SPEC}))
    assert any("defined twice" in e for e in r.errors)


def test_unknown_id_in_test(tmp_path):
    r = check(repo(tmp_path, {"e2e/dash.spec.ts": SPEC}))
    assert any("no doc defines" in e for e in r.errors)


def test_a_doc_slug_takes_its_pages_prefix(tmp_path):
    r = check(repo(tmp_path, {"docs/user_guide/other.md": PAGE, "e2e/dash.spec.ts": SPEC}))
    assert "user_guide/other/rerun" in r.matrix["user_guide"] and any("user_guide/dash/rerun" in e for e in r.errors)


def test_a_doc_marker_names_a_slug_not_a_full_id(tmp_path):
    r = check(repo(tmp_path, {"docs/user_guide/dash.md": "<!-- req: user_guide/dash/rerun -->\n", "e2e/dash.spec.ts": SPEC}))
    assert any("slug" in e for e in r.errors)


def test_malformed_marker(tmp_path):
    r = check(
        repo(
            tmp_path,
            {"e2e/a.spec.ts": "// req: Dashboard Params\n", "backend/queryview/test_a.py": "# req: dashboard/x\n"},
        )
    )
    assert len(r.errors) == 2


def test_fenced_marker_defines_nothing(tmp_path):
    r = check(repo(tmp_path, {"docs/user_guide/dash.md": f"```\n{PAGE}```\n"}))
    assert r.errors == [] and r.matrix["user_guide"] == {}


def test_non_utf8_file_does_not_crash(tmp_path):
    assert check(repo(tmp_path, {"e2e/bad.spec.ts": b"\xff\xfe"})).errors == []


def test_user_guide_id_needs_a_browser_test(tmp_path):
    r = check(
        repo(
            tmp_path,
            {
                "docs/user_guide/dash.md": PAGE,
                "backend/queryview/dash.py": '"""Doc."""\n',
                "backend/queryview/test_dash.py": "# req: user_guide/dash/rerun\n",
            },
        )
    )
    assert any("no test in e2e/" in e for e in r.errors)


def test_a_spec_in_a_subfolder_of_e2e_is_seen(tmp_path):
    r = check(repo(tmp_path, {"docs/user_guide/dash.md": PAGE, "e2e/dash/params.spec.ts": SPEC}))
    assert r.errors == []
    assert r.matrix["user_guide"] == {"user_guide/dash/rerun": ["e2e/dash/params.spec.ts"]}
    r = check(repo(tmp_path, {"e2e/dash/untagged.spec.ts": "test('x', () => {})\n"}))
    assert any("e2e/dash/untagged.spec.ts" in g for g in r.gaps)


def test_layer_proof_locations(tmp_path):
    assert check(repo(tmp_path / "g", {"docs/user_guide/dash.md": PAGE, "e2e/dash.spec.ts": SPEC})).errors == []
    page = "<!-- req: pool -->\nA pool.\n"
    for layer in ("architecture", "designs"):
        files = {f"docs/{layer}/db.md": page, "e2e/dash.spec.ts": f"// req: {layer}/db/pool\n"}
        r = check(repo(tmp_path / layer / "e2e", files))
        assert any("has no test in backend/ or frontend/" in e for e in r.errors)
        files = {f"docs/{layer}/db.md": page, "backend/queryview/test_api_db.py": f"# req: {layer}/db/pool\n"}
        r = check(repo(tmp_path / layer / "py", files))
        assert r.errors == [] and not any("test_api_db" in g for g in r.gaps)
        files = {f"docs/{layer}/db.md": page, "frontend/src/core/x.test.ts": f"// req: {layer}/db/pool\n"}
        assert check(repo(tmp_path / layer / "ts", files)).errors == []


def test_a_designs_id_marks_an_integration_test(tmp_path):
    files = {"docs/designs/db.md": "<!-- req: pool -->\n", "backend/queryview/test_x.py": "# req: designs/db/pool\n"}
    assert not any("test_x.py" in g for g in check(repo(tmp_path, files)).gaps)


def test_architecture_and_designs_ids_may_share_a_test(tmp_path):
    files = {
        "docs/architecture/api.md": "<!-- req: route -->\n",
        "docs/designs/db.md": "<!-- req: pool -->\n",
        "backend/queryview/test_x.py": "# req: architecture/api/route, designs/db/pool\n",
    }
    assert check(repo(tmp_path, files)).errors == []


def test_deployment_pages_need_no_id(tmp_path):
    files = {"docs/user_guide/docker.md": "Run it.\n", "docs/user_guide/viewer_server_docker.md": "Run it.\n"}
    assert check(repo(tmp_path, files)).gaps == []


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
        "docs/user_guide/empty.md": "text\n",
        "e2e/x.spec.ts": "test('x', () => {})\n",
        "docs/future.md": "<!-- req: b -->\n",
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
    assert main(["--root", str(repo(tmp_path, {"docs/user_guide/dash.md": "text\n", "e2e/dash.spec.ts": SPEC}))]) == 1


def test_errors_print_after_gaps(tmp_path, capsys):
    root = repo(tmp_path, {"docs/user_guide/empty.md": "text\n", "e2e/dash.spec.ts": SPEC})
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
