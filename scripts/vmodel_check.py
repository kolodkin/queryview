"""Tie every test to the doc statement it proves through `req:` IDs.

A doc defines an ID with `<!-- req: <slug> -->`, its page's path under `docs/`
giving the prefix; a test names the full ID with `// req: <id>` or `# req: <id>`. The rules live in the V-model skill,
`.claude/skills/vmodel/SKILL.md`. Errors (bad, duplicate, unknown or unproven
IDs; undocumented unit modules) always fail; gaps (untagged docs and tests)
fail only with `--strict`, which the pre-commit hook passes. Standard library only.
"""

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

LAYER_DIRS = {"requirements": "user", "system": "system", "architecture": "integration"}
ID_RE = re.compile(r"^(requirements|system|architecture)(/[a-z0-9_-]+)+$")
SLUG_RE = re.compile(r"^[a-z0-9_-]+$")
MARKER_RE = re.compile(r"^\s*(?:<!--|//|#)\s*req:\s*(.*?)\s*(?:-->)?\s*$")
ACCEPTANCE = "e2e/acceptance.spec.ts"


@dataclass
class Report:
    errors: list[str]
    gaps: list[str]
    matrix: dict[str, dict[str, list[str]]]  # layer -> ID -> test files naming it


def parse_ids(line: str) -> list[str]:
    m = MARKER_RE.match(line)
    return [i.strip() for i in m.group(1).split(",") if i.strip()] if m else []


def _read(path: Path) -> str:
    return path.read_text(errors="replace")


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _has_leading_doc(module: Path) -> bool:
    text = _read(module)
    if module.suffix == ".py":
        try:
            return bool(ast.get_docstring(ast.parse(text)))
        except SyntaxError:
            return False
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return first.startswith(("//", "/*"))


def _paired_module(test: Path) -> Path | None:
    if test.suffix == ".py":
        stem = test.stem.removeprefix("test_")
        names = [stem + ".py", f"__{stem}__.py"]  # test_main.py also proves __main__.py
    else:
        stem = test.name.split(".test.")[0]
        names = [stem + ".ts", stem + ".tsx"]
    return next((m for n in names if (m := test.with_name(n)).is_file()), None)


# Per layer: whether a test file proves its IDs, and where the error says to look.
# User and system may share a test; no other layers do.
PROOF = {
    "requirements": (lambda t: t == ACCEPTANCE, ACCEPTANCE),
    "system": (lambda t: t.startswith("e2e/"), "e2e/"),
    "architecture": (lambda t: not t.startswith("e2e/"), "backend/ or frontend/"),
}


def _definitions(root: Path, report: Report) -> dict[str, str]:
    defined: dict[str, str] = {}
    for layer in LAYER_DIRS:
        for page in sorted((root / "docs" / layer).rglob("*.md")):
            rel = _rel(root, page)
            prefix = _rel(root / "docs", page).removesuffix(".md") + "/"
            fenced, tagged = False, False
            for n, line in enumerate(_read(page).splitlines(), 1):
                if line.lstrip().startswith("```"):
                    fenced = not fenced
                for slug in [] if fenced else parse_ids(line):
                    tagged = True
                    id_ = prefix + slug  # a doc names the slug; its page gives the prefix
                    if not SLUG_RE.match(slug):
                        report.errors.append(
                            f"{rel}:{n}: {slug!r} is not a kebab-case slug (the page gives the prefix)"
                        )
                    elif id_ in defined:
                        report.errors.append(f"{rel}:{n}: {id_} defined twice (first in {defined[id_]})")
                    else:
                        defined[id_] = rel
                        report.matrix[layer][id_] = []
            if not tagged and page.name != "decisions.md":  # a decision explains a statement; no test proves it
                report.gaps.append(f"{rel}: no req: marker")
    return defined


def _test_files(root: Path) -> list[Path]:
    found = list((root / "e2e").rglob("*.spec.ts"))
    for base in ("backend/queryview", "scripts"):
        found += (root / base).rglob("test_*.py")
    found += (p for p in (root / "frontend/src").rglob("*.test.ts*") if p.suffix in (".ts", ".tsx"))
    return sorted(found)


def check(root: Path) -> Report:
    report = Report([], [], {layer: {} for layer in LAYER_DIRS})
    defined = _definitions(root, report)
    for path in _test_files(root):
        rel = _rel(root, path)
        ids, marked = [], False
        for n, line in enumerate(_read(path).splitlines(), 1):
            for id_ in parse_ids(line):
                marked = True
                if not ID_RE.match(id_):
                    report.errors.append(f"{rel}:{n}: malformed ID {id_!r}")
                elif id_ not in defined:
                    report.errors.append(f"{rel}:{n}: no doc defines {id_}")
                else:
                    ids.append(id_)
                    files = report.matrix[id_.split("/")[0]][id_]
                    if rel not in files:
                        files.append(rel)
        if rel.startswith("e2e/"):
            if not marked:
                report.gaps.append(f"{rel}: no req: marker")
        elif not any(i.startswith("architecture/") for i in ids):
            module = _paired_module(path)
            if module is None:
                report.gaps.append(f"{rel}: unit test with no module of the same name beside it")
            elif not _has_leading_doc(module):
                report.errors.append(f"{_rel(root, module)}: module has no docstring or leading comment")
    for layer, ids in report.matrix.items():
        for id_, tests in ids.items():
            proves, where = PROOF[layer]
            if not any(proves(t) for t in tests):
                report.errors.append(f"{defined[id_]}: {id_} has no test in {where}")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Tie tests to doc statements by req: IDs.")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    ap.add_argument("--strict", action="store_true", help="fail on gaps too")
    args = ap.parse_args(argv)
    if not (args.root / "docs").is_dir():
        print(f"error: {args.root} has no docs/ directory", file=sys.stderr)
        return 2
    report = check(args.root)
    for layer, ids in report.matrix.items():
        print(f"{layer} ({LAYER_DIRS[layer]}): {len(ids)} IDs")
        for id_, tests in ids.items():
            print(f"  {id_}: {', '.join(tests) or '-'}")
    for g in report.gaps:
        print(f"gap: {g}")
    for e in report.errors:  # last, so a failing hook ends on them
        print(f"error: {e}")
    return 1 if report.errors or (args.strict and report.gaps) else 0


if __name__ == "__main__":
    sys.exit(main())
