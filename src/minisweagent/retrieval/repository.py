"""Self-contained Python AST index; also executed inside Python 3.6+ task environments."""
# ruff: noqa: UP021, UP022, UP037

import ast
import io
import math
import os
import re
import subprocess
import tokenize
from collections import Counter
from pathlib import Path

EXCLUDED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "build", "dist"}
STOP_WORDS = set("a an the in on to of is it for and or with from this that be as def class return import self".split())


def terms(text: str) -> "list[str]":
    words = re.findall(r"[A-Za-z_]\w*", text)
    words += re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)", " ".join(words).replace("_", " "))
    return [word.lower() for word in words if word.lower() not in STOP_WORDS]


class SymbolVisitor(ast.NodeVisitor):
    def __init__(self, path: str, source: str):
        self.path = path
        self.lines = source.splitlines()
        self.owners: "list[str]" = []
        self.owner_kinds: "list[str]" = []
        self.symbols: "list[dict]" = []

    def visit_definition(self, node: "ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef") -> None:
        name = ".".join([*self.owners, node.name])
        start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
        end = getattr(node, "end_lineno", None) or max(
            getattr(child, "lineno", node.lineno) for child in ast.walk(node)
        )
        definition = "\n".join(self.lines[node.lineno - 1 : node.body[0].lineno])
        depth = 0
        signature = self.lines[node.lineno - 1].strip()
        for token in tokenize.generate_tokens(io.StringIO(definition).readline):
            if token.type != tokenize.OP:
                continue
            if token.string in "([{":
                depth += 1
            elif token.string in ")]}":
                depth -= 1
            elif token.string == ":" and depth == 0:
                row, column = token.start
                signature = " ".join(
                    "\n".join(definition.splitlines()[: row - 1] + [definition.splitlines()[row - 1][:column]]).split()
                )
                break
        if isinstance(node, ast.ClassDef):
            signature = signature.replace(f"class {node.name}", f"class {name}", 1)
            kind = "class"
        else:
            signature = signature.replace(f"def {node.name}", f"def {name}", 1)
            kind = "method" if self.owner_kinds and self.owner_kinds[-1] == "class" else "function"
        self.symbols.append(
            {
                "path": self.path,
                "name": name,
                "kind": kind,
                "start_line": start,
                "end_line": end,
                "signature": signature[:500],
                "docstring": (ast.get_docstring(node) or "")[:300],
                "source": "\n".join(self.lines[start - 1 : end])[:12000],
            }
        )
        self.owners.append(node.name)
        self.owner_kinds.append(kind)
        self.generic_visit(node)
        self.owner_kinds.pop()
        self.owners.pop()

    visit_ClassDef = visit_definition
    visit_FunctionDef = visit_definition
    visit_AsyncFunctionDef = visit_definition


class RepositoryIndex:
    def __init__(self, root: Path):
        self.root = root.resolve()
        if not self.root.is_dir():
            raise ValueError(f"Repository directory does not exist: {self.root}")
        self.symbols: "list[dict]" = []
        self.skipped: "list[dict]" = []
        self.file_count = 0
        tracked = subprocess.run(
            ["git", "-C", str(self.root), "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "*.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        paths = [self.root / p for p in tracked.stdout.split("\0") if p]
        if tracked.returncode != 0:
            paths = []
            for directory, directories, files in os.walk(str(self.root)):
                directories[:] = [name for name in directories if name not in EXCLUDED_DIRS]
                paths.extend(Path(directory) / name for name in files if name.endswith(".py"))
        for path in sorted(paths):
            if path.is_symlink() or self.root not in path.resolve().parents:
                continue
            relative = path.relative_to(self.root)
            if EXCLUDED_DIRS.intersection(relative.parts) or not path.is_file():
                continue
            if path.stat().st_size > 1_000_000:
                self.skipped.append({"path": str(relative), "reason": "file exceeds 1 MB"})
                continue
            try:
                with tokenize.open(path) as handle:
                    source = handle.read()
                tree = ast.parse(source)
            except (SyntaxError, UnicodeError, OSError) as exc:
                self.skipped.append({"path": str(relative), "reason": type(exc).__name__})
                continue
            self.file_count += 1
            visitor = SymbolVisitor(relative.as_posix(), source)
            visitor.visit(tree)
            self.symbols.extend(visitor.symbols)
            self.symbols.append(
                {
                    "path": relative.as_posix(),
                    "name": "<module>",
                    "kind": "module",
                    "start_line": 1,
                    "end_line": max(1, len(source.splitlines())),
                    "signature": relative.as_posix(),
                    "docstring": (ast.get_docstring(tree) or "")[:300],
                    "source": source,
                }
            )
        self.documents = [
            Counter(terms(f"{s['path']} {s['signature']} {s['docstring']} {s['source']}")) for s in self.symbols
        ]
        self.lengths = [sum(doc.values()) for doc in self.documents]
        self.average_length = sum(self.lengths) / max(1, len(self.lengths))
        self.document_frequency = Counter(term for doc in self.documents for term in doc)
        file_documents = [doc for symbol, doc in zip(self.symbols, self.documents) if symbol["kind"] == "module"]
        self.file_document_frequency = Counter(term for doc in file_documents for term in doc)
        self.file_average_length = sum(sum(doc.values()) for doc in file_documents) / max(1, self.file_count)

    def search(self, query: str, limit: int = 10, file_only: bool = False) -> "list[dict]":
        query_terms = set(terms(query))
        ranked = []
        document_frequency = self.file_document_frequency if file_only else self.document_frequency
        document_count = self.file_count if file_only else len(self.symbols)
        average_length = self.file_average_length if file_only else self.average_length
        for symbol, document, length in zip(self.symbols, self.documents, self.lengths):
            if file_only and symbol["kind"] != "module":
                continue
            score = 0.0
            for term in query_terms & document.keys():
                frequency = document[term]
                idf = math.log(1 + (document_count - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
                score += idf * frequency * 2.5 / (frequency + 1.5 * (0.25 + 0.75 * length / average_length))
            if symbol["kind"] != "module":
                score += 2 * len(query_terms & set(terms(symbol["name"])))
            if score > 0:
                ranked.append({**{k: v for k, v in symbol.items() if k != "source"}, "score": round(score, 6)})
        return sorted(ranked, key=lambda s: (-s["score"], s["path"], s["start_line"], s["name"]))[:limit]

    def ranked_files(self, query: str, file_only: bool = False) -> "list[str]":
        return list(dict.fromkeys(symbol["path"] for symbol in self.search(query, len(self.symbols), file_only)))

    def repo_map(self, query: str, max_chars: int = 6000) -> str:
        candidates = (
            self.search(query, limit=len(self.symbols))
            if query.strip()
            else sorted(
                ({k: v for k, v in s.items() if k != "source"} for s in self.symbols if s["kind"] != "module"),
                key=lambda s: (s["path"], s["start_line"], s["name"]),
            )
        )
        output = (
            f"Python repository: {self.file_count} files; {len(self.symbols)} entries; {len(self.skipped)} skipped.\n"
        )
        marker = "[map truncated to character budget]\n"
        omitted = False
        for symbol in candidates:
            line = f"{symbol['path']}:{symbol['start_line']}-{symbol['end_line']} {symbol['signature']}\n"
            if len(output) + len(line) > max_chars - len(marker):
                omitted = True
                continue
            output += line
        if omitted:
            output += marker
        return output[:max_chars]


def retrieve(args: dict) -> dict:
    index = RepositoryIndex(Path(args.get("root", ".")))
    if args["operation"] == "repo_map":
        return {"output": index.repo_map(args.get("query", ""), args.get("max_chars", 6000)), "returncode": 0}
    return {
        "output": __import__("json").dumps(
            {
                "matches": index.search(args["query"], args.get("limit", 10)),
                "files_indexed": index.file_count,
                "skipped": index.skipped,
            }
        ),
        "returncode": 0,
    }
