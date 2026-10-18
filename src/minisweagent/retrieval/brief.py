"""Deterministic issue-to-repository brief built from the AST index.

This module is intentionally self-contained and stdlib-only.  ``brief_tool.py``
embeds this file together with ``repository.py`` inside the task environment,
so it must not import the ``minisweagent`` package at runtime.

The brief is not a model call and does not read gold patches.  It only routes
high-signal issue text (paths, stack frames, symbols) to candidate locations and
adds a short, budgeted list of BM25 candidates.
"""

import re
from collections import Counter
from pathlib import Path

PATH_SUFFIXES = (
    "py",
    "pyi",
    "toml",
    "cfg",
    "ini",
    "yaml",
    "yml",
    "json",
    "md",
    "rst",
    "txt",
    "js",
    "jsx",
    "ts",
    "tsx",
    "go",
    "java",
    "c",
    "cc",
    "cpp",
    "h",
    "hpp",
    "rs",
    "sh",
    "sql",
    "html",
    "css",
)
SUPPORT_DIRS = {"test", "tests", "testing", "docs", "doc", "tutorials", "examples", "benchmarks"}
PYTHON_KEYWORDS = set(
    "and as assert async await break class continue def del elif else except False finally for from global "
    "if import in is lambda None nonlocal not or pass raise return True try while with yield".split()
)
HINT_SKIP_NAMES = PYTHON_KEYWORDS | {
    "self",
    "cls",
    "http",
    "https",
    "com",
    "org",
    "github",
    "python",
    "python3",
    "str",
    "int",
    "float",
    "bool",
    "list",
    "dict",
    "set",
    "tuple",
    "object",
    "e.g",
    "i.e",
    "etc",
    "fig",
    "eq",
    "vs",
    "cf",
    "al",
    "description",
    "issue",
    "bug",
    "api",
    "url",
    "pr",
    "HTTP",
    "API",
    "URL",
    "PR",
    "HTML",
    "JSON",
    "YAML",
    "print",
    "range",
    "open",
    "super",
    "type",
    "isinstance",
    "getattr",
    "setattr",
    "hasattr",
    "enumerate",
    "zip",
    "map",
    "filter",
    "sorted",
    "sum",
    "min",
    "max",
    "any",
    "all",
    "repr",
    "format",
    "input",
    "vars",
    "dir",
    "id",
    "hash",
    "iter",
    "next",
    "round",
    "abs",
}
_PATH_RE = re.compile(
    r"(?<![\w./-])((?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.(?:{}))".format("|".join(PATH_SUFFIXES))
)
_FRAME_RE = re.compile(r'File "([^"]+)", line (\d+)(?:, in ([A-Za-z_]\w*))?')
_BACKTICK_RE = re.compile(r"`([^`\n]{1,160})`")
_DEF_RE = re.compile(r"\b(?:def|class)\s+([A-Za-z_]\w*)")
_EXCEPTION_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]*(?:Error|Exception))\b")
_QUALIFIED_RE = re.compile(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\b")
_IDENT_RE = re.compile(r"\b([A-Za-z_]\w*)\b")
_TEST_RE = re.compile(r"\b(test_[A-Za-z0-9_]+)\b")


def is_support_path(path):
    """Whether a path is test/docs/example material rather than product code."""
    return any(part in SUPPORT_DIRS for part in str(path).split("/")[:-1])


def _clean_path(value):
    path = str(value).strip().strip("'\"`()[]{}.,;:")
    if path.startswith("./"):
        path = path[2:]
    if path.startswith("/testbed/"):
        path = path[len("/testbed/") :]
    while path.startswith("/"):
        path = path[1:]
    return path


def _clean_symbol(value):
    symbol = str(value).strip().strip("'\"`")
    for marker in ("(", "[", " "):
        if marker in symbol:
            symbol = symbol.split(marker, 1)[0]
    symbol = symbol.rstrip(".,;:)]}>")
    if symbol.startswith("self."):
        symbol = symbol[len("self.") :]
    if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", symbol or ""):
        return ""
    if symbol in HINT_SKIP_NAMES:
        return ""
    if any(part in HINT_SKIP_NAMES for part in symbol.split(".")):
        return ""
    return symbol


def _looks_code_like(name):
    if name in HINT_SKIP_NAMES:
        return False
    if "_" in name:
        return True
    if name.endswith(("Error", "Exception")):
        return True
    # CamelCase with at least two humps (URLResolver, ConfigLoader), but not
    # ordinary prose words such as Description or Python.
    humps = re.findall(r"[A-Z][a-z0-9]*", name)
    return len(humps) >= 2


def extract_issue_hints(issue):
    """Extract paths, stack frames, and code-like symbols from an issue.

    Conservative by design: prose words such as ``shared`` or ``clear`` are not
    extracted unless they appear as a path, qualified name, backticked token, or
    underscore/CamelCase identifier.  BM25 still sees the full issue text.
    """
    text = str(issue or "")
    paths = []
    frames = []
    symbols = []
    exceptions = []
    tests = []

    for match in _FRAME_RE.finditer(text):
        path = _clean_path(match.group(1))
        if path:
            paths.append(path)
            frames.append({"path": path, "line": int(match.group(2)), "function": (match.group(3) or "").strip()})
    for match in _PATH_RE.finditer(text):
        path = _clean_path(match.group(1))
        if path:
            paths.append(path)
    for match in _BACKTICK_RE.finditer(text):
        candidate = match.group(1).strip()
        if "/" in candidate or "\\" in candidate:
            continue
        symbol = _clean_symbol(candidate)
        if symbol:
            symbols.append(symbol)
    for match in _DEF_RE.finditer(text):
        symbols.append(match.group(1))
    for match in _QUALIFIED_RE.finditer(text):
        candidate = match.group(1)
        if candidate.rsplit(".", 1)[-1].lower() in PATH_SUFFIXES:
            continue
        symbol = _clean_symbol(candidate)
        if symbol:
            symbols.append(symbol)
    for match in _IDENT_RE.finditer(text):
        candidate = match.group(1)
        if _looks_code_like(candidate) and candidate not in HINT_SKIP_NAMES:
            symbols.append(candidate)
    for match in _EXCEPTION_RE.finditer(text):
        exceptions.append(match.group(1))
        symbols.append(match.group(1))
    for match in _TEST_RE.finditer(text):
        tests.append(match.group(1))
        symbols.append(match.group(1))

    def unique(values):
        return list(dict.fromkeys(values))

    unique_symbols = unique(symbols)
    unique_symbols.sort(key=lambda value: text.find(value) if text.find(value) >= 0 else len(text) + 1)
    return {
        "paths": unique(paths)[:20],
        "frames": frames[:10],
        "symbols": unique_symbols[:30],
        "exceptions": unique(exceptions)[:10],
        "tests": unique(tests)[:10],
    }


def _resolve_path(index, value):
    """Resolve a hint to a repository-relative file, or return an empty string.

    Issue tracebacks often contain absolute paths from another machine.  If the
    exact path does not exist, try progressively shorter suffixes and accept the
    longest suffix that identifies a file in this checkout.
    """
    raw = _clean_path(value)
    if not raw:
        return ""
    root = Path(index.root).resolve()
    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        if resolved != root and root not in resolved.parents:
            resolved = None
        if resolved is not None and resolved.is_file():
            return resolved.relative_to(root).as_posix()
    else:
        try:
            resolved = (root / candidate).resolve()
        except OSError:
            resolved = None
        if resolved is not None and (resolved == root or root in resolved.parents) and resolved.is_file():
            return resolved.relative_to(root).as_posix()

    parts = [part for part in raw.replace("\\", "/").split("/") if part and part not in {".", ".."}]
    for length in range(len(parts) - 1, 0, -1):
        suffix = "/".join(parts[-length:])
        try:
            resolved = (root / suffix).resolve()
        except OSError:
            continue
        if (resolved == root or root in resolved.parents) and resolved.is_file():
            return resolved.relative_to(root).as_posix()
    return ""


def _containing_symbol(index, path, line):
    """The smallest indexed definition containing ``path:line``."""
    matches = [
        symbol
        for symbol in index.symbols
        if symbol.get("path") == path
        and symbol.get("kind") != "module"
        and symbol.get("start_line", 0) <= line <= symbol.get("end_line", 0)
    ]
    matches.sort(key=lambda symbol: (symbol["end_line"] - symbol["start_line"], -symbol["start_line"]))
    return matches[0] if matches else None


def _definitions_for(index, symbol, limit=3):
    try:
        matches = index.find(symbol, limit=limit)
    except (TypeError, ValueError):
        return []
    if not matches and "." in symbol:
        try:
            matches = index.find(symbol.rsplit(".", 1)[-1], limit=limit)
        except (TypeError, ValueError):
            matches = []
    # A variable named ``mail`` is rarely the definition the issue means when it
    # writes ``django.core.mail``; prefer callable/class definitions.
    preferred = [entry for entry in matches if entry.get("kind") != "variable"]
    return preferred or matches


def _is_specific_symbol(symbol):
    """Whether a hint is likely a code symbol rather than a prose token."""
    return (
        "." in symbol
        or "_" in symbol
        or bool(re.search(r"[a-z][A-Z]", symbol))
        or symbol.endswith(("Error", "Exception"))
    )


def _layout_lines(index, limit=6):
    counts = Counter()
    for symbol in index.symbols:
        if symbol.get("kind") != "module":
            continue
        path = symbol.get("path", "")
        top = path.split("/", 1)[0] if "/" in path else "."
        counts[top] += 1
    parts = []
    for name, count in counts.most_common(limit):
        parts.append(f"{name}/ ({count})" if name != "." else f"./ ({count})")
    return parts


def _display_hint_path(path, keep=3):
    parts = [part for part in str(path).replace("\\", "/").split("/") if part]
    if len(parts) > keep + 1:
        return ".../" + "/".join(parts[-keep:])
    return "/".join(parts)


def brief_files(index, issue, max_files=6):
    """Return the ordered candidate paths a brief would show.

    This is intentionally derived from the rendered brief so offline evaluation
    measures exactly what the agent sees, not a second selection path.
    """
    text = build_brief(index, issue, max_chars=20000, max_files=max_files)
    return re.findall(r"^\s+\d+\. (\S+) \[", text, re.MULTILINE)


def build_brief(index, issue, max_chars=3000, max_files=6):
    """Build a deterministic repository brief for one issue.

    The output is deliberately location-oriented: paths, definitions, and a
    suggested first action.  Code snippets remain the job of ``code_context`` so
    the brief can stay inside a small prompt budget.
    """
    try:
        max_chars = int(max_chars)
    except (TypeError, ValueError):
        max_chars = 3000
    max_chars = max(400, min(20000, max_chars))
    try:
        max_files = int(max_files)
    except (TypeError, ValueError):
        max_files = 6
    max_files = max(1, min(20, max_files))

    hints = extract_issue_hints(issue)
    path_candidates = []
    missing_paths = []
    for path in hints["paths"]:
        resolved = _resolve_path(index, path)
        if resolved:
            if resolved not in [item["path"] for item in path_candidates]:
                path_candidates.append({"path": resolved, "reason": "issue path", "line": 0})
        else:
            missing_paths.append(path)

    frame_candidates = []
    for frame in hints["frames"]:
        resolved = _resolve_path(index, frame["path"])
        if not resolved:
            continue
        item = {"path": resolved, "reason": "stack frame", "line": frame["line"]}
        if item not in frame_candidates:
            frame_candidates.append(item)
        symbol = _containing_symbol(index, resolved, frame["line"])
        if symbol and symbol.get("name"):
            hints["symbols"].append(symbol["name"])

    symbol_definitions = []
    resolved_symbols = []
    seen_definitions = set()
    has_path_hint = bool(path_candidates or frame_candidates)
    for symbol in hints["symbols"]:
        if has_path_hint and not _is_specific_symbol(symbol):
            continue
        matches = sorted(
            _definitions_for(index, symbol, limit=3),
            key=lambda entry: (is_support_path(entry["path"]), entry["path"], entry["start_line"]),
        )
        for entry in matches:
            key = (entry["path"], entry["start_line"], entry["name"])
            if key in seen_definitions:
                continue
            seen_definitions.add(key)
            symbol_definitions.append(entry)
            resolved_symbols.append((symbol, entry))

    bm25_paths = []
    try:
        bm25_paths = index.context_files(issue, max_files=max_files)
    except (AttributeError, TypeError, ValueError, OSError):
        bm25_paths = []

    ordered_paths = []
    for item in frame_candidates + path_candidates:
        if item["path"] not in [entry["path"] for entry in ordered_paths]:
            ordered_paths.append(item)
    for entry in symbol_definitions:
        if entry["path"] not in [item["path"] for item in ordered_paths]:
            ordered_paths.append({"path": entry["path"], "reason": "symbol definition", "line": 0})
    for path in bm25_paths:
        if path not in [item["path"] for item in ordered_paths]:
            ordered_paths.append({"path": path, "reason": "BM25 candidate", "line": 0})
    ordered_paths = ordered_paths[:max_files]

    definitions_by_path = {}
    for entry in symbol_definitions:
        definitions_by_path.setdefault(entry["path"], []).append(entry)

    lines = []
    lines.append(
        "Repository brief (deterministic; generated from the issue text and a Python AST index)."
    )
    lines.append(
        f"Python index: {index.file_count} files; {len(index.symbols)} entries; {len(index.skipped)} skipped."
    )
    layout = _layout_lines(index)
    if layout:
        lines.append("Layout: " + ", ".join(layout) + ".")
    if hints["paths"] or hints["symbols"] or hints["frames"]:
        lines.append("Issue hints:")
        if hints["paths"]:
            lines.append("  paths: " + ", ".join(_display_hint_path(path) for path in hints["paths"][:5]))
        if hints["symbols"]:
            lines.append("  symbols: " + ", ".join(hints["symbols"][:8]))
        if hints["frames"]:
            frame_text = []
            for frame in hints["frames"][:5]:
                suffix = f" in {frame['function']}" if frame["function"] else ""
                frame_text.append(f"{_display_hint_path(frame['path'])}:{frame['line']}{suffix}")
            lines.append("  stack frames: " + "; ".join(frame_text))
        if missing_paths:
            lines.append(
                "  paths not found in this checkout: "
                + ", ".join(_display_hint_path(path) for path in missing_paths[:5])
            )

    first_path = ordered_paths[0]["path"] if (frame_candidates or path_candidates or symbol_definitions) else ""
    resolved_hint = bool(frame_candidates or path_candidates or symbol_definitions)
    lines.append("Suggested first action:")
    if first_path:
        line_note = ""
        if ordered_paths[0].get("line"):
            line_note = f" around line {ordered_paths[0]['line']}"
        lines.append(f"  - Inspect {first_path}{line_note} first (read_file/refined_read_file).")
    if resolved_symbols:
        symbol, definition = resolved_symbols[0]
        lines.append(
            f"  - {symbol} resolves to {definition['path']}:{definition['start_line']} "
            f"({definition['kind']} {definition['name']})."
        )
        if len(resolved_symbols) > 1:
            alternative_symbol, alternative = resolved_symbols[1]
            if alternative["path"] != definition["path"]:
                lines.append(
                    f"  - Also consider {alternative_symbol} at {alternative['path']}:"
                    f"{alternative['start_line']} ({alternative['kind']} {alternative['name']})."
                )
    if not resolved_hint:
        if hints["paths"] or hints["symbols"] or hints["frames"]:
            lines.append(
                "  - The high-signal hints did not resolve in this checkout. Use code_context/code_search "
                "with the issue keywords, then verify the candidate path or symbol before editing."
            )
        else:
            lines.append(
                "  - No decisive path/symbol hint. Use code_context/code_search/repo_map with the issue "
                "keywords, then read the most specific candidate."
            )
    lines.append(
        "  - After reading: state one hypothesis, make the smallest edit, run a focused test. "
        "If two hypotheses fail, stop broad searching and reproduce or submit the best patch."
    )

    if ordered_paths:
        lines.append("Candidate files:" if resolved_hint else "Fallback BM25 candidates:")
        for number, item in enumerate(ordered_paths, 1):
            suffix = f" (line {item['line']})" if item.get("line") else ""
            lines.append(f"  {number}. {item['path']} [{item['reason']}{suffix}]")
            for entry in definitions_by_path.get(item["path"], [])[:2]:
                lines.append(
                    f"     - {entry['kind']} {entry['name']} lines {entry['start_line']}-{entry['end_line']}"
                )
    if symbol_definitions:
        lines.append("Candidate definitions:")
        for entry in symbol_definitions[:8]:
            lines.append(
                f"  - {entry['path']}:{entry['start_line']}-{entry['end_line']} "
                f"{entry['kind']} {entry['name']}"
            )
    if not ordered_paths:
        lines.append("Candidate files: none; the index found no Python candidate for this issue.")

    marker = "\n[brief truncated to character budget]"
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[: max(0, max_chars - len(marker))].rstrip() + marker
    return text
