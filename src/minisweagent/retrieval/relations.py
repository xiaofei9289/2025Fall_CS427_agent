"""Lightweight, stdlib-only Python relation scan for ``find_references``.

This module is embedded next to ``repository.py`` inside the task environment.
It deliberately avoids a full type-resolution engine: it records name, call,
attribute, import, and base-class references that textually match the requested
symbol. The result is a starting point for impact analysis, not a proof.
"""

import ast
from pathlib import Path

MAX_REFERENCES = 200
MAX_CONTEXT_CHARS = 12000


def _dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _matching(name, targets):
    if not name:
        return False
    return name in targets or name.rsplit(".", 1)[-1] in targets


class RelationVisitor(ast.NodeVisitor):
    """Collect only references whose name matches one of ``targets``."""

    def __init__(self, path, targets):
        self.path = path
        self.targets = targets
        self.owners = []
        self.entries = []
        self._seen = set()

    def _owner(self):
        return ".".join(self.owners) if self.owners else "<module>"

    def _record(self, name, node, kind):
        if not _matching(name, self.targets):
            return
        line = getattr(node, "lineno", 0)
        column = getattr(node, "col_offset", 0)
        owner = self._owner()
        key = (line, column, name, kind, owner)
        if key in self._seen:
            return
        self._seen.add(key)
        self.entries.append(
            {
                "path": self.path,
                "line": line,
                "column": column,
                "name": name,
                "kind": kind,
                "owner": owner,
            }
        )

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load):
            self._record(node.id, node, "read")
        self.generic_visit(node)

    def visit_Attribute(self, node):
        if isinstance(node.ctx, ast.Load):
            full = _dotted(node)
            self._record(node.attr, node, "attribute")
            if full and full != node.attr:
                self._record(full, node, "attribute")
        self.generic_visit(node)

    def visit_Call(self, node):
        full = _dotted(node.func)
        if full:
            self._record(full, node, "call")
            if "." in full:
                self._record(full.rsplit(".", 1)[-1], node, "call")
        self.generic_visit(node)

    def _visit_definition(self, node):
        self.owners.append(node.name)
        for base in getattr(node, "bases", []):
            name = _dotted(base)
            if name:
                self._record(name, base, "base")
        self.generic_visit(node)
        self.owners.pop()

    visit_ClassDef = _visit_definition
    visit_FunctionDef = _visit_definition
    visit_AsyncFunctionDef = _visit_definition

    def visit_Import(self, node):
        for alias in node.names:
            self._record(alias.name, node, "import")
            if alias.asname:
                self._record(alias.asname, node, "import")
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        for alias in node.names:
            self._record(alias.name, node, "import")
            if alias.asname:
                self._record(alias.asname, node, "import")
        self.generic_visit(node)


def _module_paths(index):
    paths = []
    for symbol in index.symbols:
        if symbol.get("kind") == "module" and symbol.get("path"):
            paths.append(symbol["path"])
    return sorted(dict.fromkeys(paths))


def find_references(index, symbol, limit=50, path_filter=""):
    """Return definitions plus matching references for ``symbol``.

    ``path_filter`` is a repository-relative path; when set, only that file is
    scanned. References are capped at ``limit`` (and internally at
    ``MAX_REFERENCES`` before sorting/truncation).
    """
    symbol = str(symbol or "").strip()
    if symbol.startswith("self."):
        symbol = symbol[len("self.") :]
    if not symbol:
        return {"definitions": [], "references": [], "files_scanned": 0, "truncated": False}
    if not isinstance(limit, int) or limit < 1:
        limit = 50
    limit = min(limit, 100)
    definitions = index.find(symbol, limit=20)
    if not definitions and "." in symbol:
        definitions = index.find(symbol.rsplit(".", 1)[-1], limit=20)
    targets = {symbol, symbol.rsplit(".", 1)[-1]}
    for entry in definitions:
        targets.add(entry["name"])
        targets.add(entry["name"].rsplit(".", 1)[-1])

    paths = _module_paths(index)
    if path_filter:
        normalized = str(path_filter).replace("\\", "/").lstrip("./")
        paths = [path for path in paths if path == normalized or path.endswith("/" + normalized)]

    entries = []
    files_scanned = 0
    root = Path(index.root)
    for relative in paths:
        try:
            source = (root / relative).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not any(target in source for target in targets if len(target) >= 2):
            continue
        files_scanned += 1
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError):
            continue
        visitor = RelationVisitor(relative, targets)
        visitor.visit(tree)
        entries.extend(visitor.entries)
        if len(entries) >= MAX_REFERENCES * 4:
            break

    priority = {"call": 0, "base": 1, "import": 2, "attribute": 3, "read": 4}
    deduped = {}
    for entry in entries:
        key = (entry["path"], entry["line"], entry["name"], entry["owner"])
        previous = deduped.get(key)
        if previous is None or priority.get(entry["kind"], 9) < priority.get(previous["kind"], 9):
            deduped[key] = entry
    ordered = sorted(deduped.values(), key=lambda item: (item["path"], item["line"], item["column"], item["kind"]))
    truncated = len(ordered) > limit
    return {
        "definitions": definitions,
        "references": ordered[:limit],
        "files_scanned": files_scanned,
        "truncated": truncated,
    }


def _context(path, line, context_lines):
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    start = max(0, line - 1 - context_lines)
    end = min(len(lines), line + context_lines)
    parts = []
    for position in range(start, end):
        marker = ">>>" if position == line - 1 else "   "
        parts.append(f"{marker} {position + 1:4d}: {lines[position]}")
    return "\n".join(parts)


def format_references(index, result, context_lines=1, max_chars=MAX_CONTEXT_CHARS):
    """Render a compact text report for the ``find_references`` tool."""
    definitions = result.get("definitions", [])
    references = result.get("references", [])
    lines = []
    if definitions:
        lines.append(f"Definitions for '{definitions[0]['name']}':")
        for entry in definitions:
            lines.append(f"  {entry['path']}:{entry['start_line']} {entry['kind']} {entry['name']}")
    else:
        lines.append("Definitions: none")
    lines.append(f"References: {len(references)}" + (" (truncated)" if result.get("truncated") else ""))
    root = Path(index.root)
    if not references:
        lines.append("  No matching references found in indexed Python files.")
    for entry in references:
        lines.append(
            f"  {entry['path']}:{entry['line']} [{entry['kind']}] in {entry['owner']} ({entry['name']})"
        )
        excerpt = _context(root / entry["path"], entry["line"], context_lines)
        if excerpt:
            lines.extend("    " + line for line in excerpt.splitlines())
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[: max(0, max_chars - 30)].rstrip() + "\n[references truncated]"
    return text
