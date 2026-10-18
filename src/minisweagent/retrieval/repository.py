"""Self-contained Python AST index; also executed inside Python 3.6+ task environments."""
# ruff: noqa: UP021, UP022, UP037

import ast
import gzip
import hashlib
import io
import json
import math
import os
import re
import subprocess
import tempfile
import tokenize
from collections import Counter
from pathlib import Path

EXCLUDED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "build", "dist"}
STOP_WORDS = set("a an the in on to of is it for and or with from this that be as def class return import self".split())
SUPPORT_DIRS = {"test", "tests", "docs", "doc", "tutorials", "examples", "benchmarks"}
GENERIC_NAMES = set(
    "name value data id pk get set save delete update create read write close items keys values copy format join "
    "split strip lower upper append extend insert remove pop count index sort reverse run clean validate default "
    "request context response".split()
)
CACHE_VERSION = 4
CACHE_MIN_FILES = 100


def terms(text: str) -> "list[str]":
    words = re.findall(r"[A-Za-z_]\w*", text)
    words += re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)", " ".join(words).replace("_", " "))
    return [word.lower() for word in words if word.lower() not in STOP_WORDS]


def is_support_path(path: str) -> bool:
    """Whether a path is test/docs/example material rather than product code."""
    return any(part in SUPPORT_DIRS for part in path.split("/")[:-1])


class SymbolVisitor(ast.NodeVisitor):
    def __init__(self, path: str, source: str):
        self.path = path
        self.lines = source.splitlines()
        self.owners: "list[str]" = []
        self.owner_kinds: "list[str]" = []
        self.symbols: "list[dict]" = []
        self.variables: "list[dict]" = []
        self.references: "Counter" = Counter()

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

    def _target_names(self, target: "ast.AST") -> "list[str]":
        if isinstance(target, ast.Name):
            return [target.id]
        if isinstance(target, (ast.Tuple, ast.List)):
            names: "list[str]" = []
            for element in target.elts:
                names.extend(self._target_names(element))
            return names
        if isinstance(target, ast.Starred):
            return self._target_names(target.value)
        return []

    def _record_variables(self, node: "ast.AST", names: "list[str]") -> None:
        for name in dict.fromkeys(names):
            start = node.lineno
            end = getattr(node, "end_lineno", None) or start
            source = "\n".join(self.lines[start - 1 : end])[:2000]
            self.variables.append(
                {
                    "path": self.path,
                    "name": ".".join([*self.owners, name]),
                    "kind": "variable",
                    "start_line": start,
                    "end_line": end,
                    "signature": source.splitlines()[0].strip()[:500] if source else name,
                    "docstring": "",
                    "source": source,
                }
            )

    def visit_Assign(self, node: "ast.Assign") -> None:
        names = []
        for target in node.targets:
            names.extend(self._target_names(target))
        self._record_variables(node, names)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: "ast.AnnAssign") -> None:
        self._record_variables(node, self._target_names(node.target))
        self.generic_visit(node)

    def visit_Name(self, node: "ast.Name") -> None:
        if isinstance(node.ctx, ast.Load):
            self.references[node.id] += 1


class RepositoryIndex:
    """AST symbol index plus BM25, repo map, and budgeted code context.

    The index is deliberately self-contained: ``code_search.py`` injects this
    source file into Docker/Local environments and runs it there. Split
    retrieval modules would need a bundling step before they could be injected.
    """

    def __init__(
        self,
        root: Path,
        cache: bool = True,
        cache_dir: "str | None" = None,
        cache_min_files: int = CACHE_MIN_FILES,
    ):
        self.root = root.resolve()
        if not self.root.is_dir():
            raise ValueError(f"Repository directory does not exist: {self.root}")
        self._cache_enabled = cache and os.environ.get("MINISWEAGENT_INDEX_CACHE", "1") != "0"
        self._cache_dir = Path(cache_dir) if cache_dir else Path(tempfile.gettempdir()) / "minisweagent-index-cache"
        self._cache_min_files = cache_min_files
        self.symbols: "list[dict]" = []
        self.variables: "list[dict]" = []
        self.reference_counts: "Counter" = Counter()
        self.skipped: "list[dict]" = []
        self.file_count = 0
        self.documents: "list[Counter]" = []
        self.lengths: "list[int]" = []
        self.average_length = 0.0
        self.document_frequency: "Counter" = Counter()
        self.file_document_frequency: "Counter" = Counter()
        self.file_average_length = 0.0
        self.symbol_count = 0
        self.symbol_document_frequency: "Counter" = Counter()
        self.symbol_average_length = 0.0
        self.importance: "list[float]" = []

        files = list(self._iter_python_files())
        fingerprint = self._fingerprint(files)
        if self._cache_enabled and self._load_cache(fingerprint):
            return
        self._build(files)
        self.importance = self._compute_importance()
        if self._cache_enabled and self.file_count >= self._cache_min_files:
            self._save_cache(fingerprint)

    def _iter_python_files(self):
        """Yield ``(path, relative_path)`` for Python files in the workspace."""
        try:
            tracked = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.root),
                    "ls-files",
                    "--cached",
                    "--others",
                    "--exclude-standard",
                    "-z",
                    "--",
                    "*.py",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
            )
        except OSError:
            tracked = None
        if tracked is not None and tracked.returncode == 0:
            paths = [self.root / p for p in tracked.stdout.split("\0") if p]
        else:
            paths = []
            for directory, directories, files in os.walk(str(self.root)):
                directories[:] = [name for name in directories if name not in EXCLUDED_DIRS]
                paths.extend(Path(directory) / name for name in files if name.endswith(".py"))
        for path in sorted(paths):
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if path.is_symlink() or self.root not in resolved.parents:
                continue
            relative = path.relative_to(self.root)
            if EXCLUDED_DIRS.intersection(relative.parts) or not path.is_file():
                continue
            yield path, relative

    def _fingerprint(self, files: "list[tuple[Path, Path]]") -> str:
        """Cheap change detector for cache validation; never hashes file contents."""
        digest = hashlib.sha1()
        for path, relative in files:
            try:
                stat = path.stat()
            except OSError:
                continue
            digest.update(
                f"{relative.as_posix()}\0{stat.st_mtime_ns}\0{stat.st_ctime_ns}\0{stat.st_size}\n".encode(
                    "utf-8", "replace"
                )
            )
        return digest.hexdigest()

    def _build(self, files: "list[tuple[Path, Path]]") -> None:
        for path, relative in files:
            try:
                size = path.stat().st_size
            except OSError as exc:
                self.skipped.append({"path": str(relative), "reason": type(exc).__name__})
                continue
            if size > 1_000_000:
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
            self.variables.extend(visitor.variables)
            self.reference_counts.update(visitor.references)
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
        symbol_documents = [
            (doc, length)
            for symbol, doc, length in zip(self.symbols, self.documents, self.lengths)
            if symbol["kind"] != "module"
        ]
        self.symbol_count = len(symbol_documents)
        self.symbol_document_frequency = Counter(term for doc, _ in symbol_documents for term in doc)
        self.symbol_average_length = sum(length for _, length in symbol_documents) / max(1, self.symbol_count)

    def _compute_importance(self) -> "list[float]":
        """A cheap reference-count proxy for the empty-query repo map.

        A full Aider-style reference graph is intentionally out of scope here.
        Methods inherit their owner class's reference count, which avoids
        letting ubiquitous attribute names such as ``name`` dominate the map.
        """
        counts = self.reference_counts
        scores = []
        for symbol in self.symbols:
            if symbol["kind"] == "module":
                scores.append(0.0)
                continue
            simple = symbol["name"].rsplit(".", 1)[-1]
            if symbol["kind"] == "method":
                owner = symbol["name"].rsplit(".", 1)[0].rsplit(".", 1)[-1]
                score = float(counts.get(owner, 0)) * 0.5
                if simple not in GENERIC_NAMES:
                    score += float(counts.get(simple, 0)) * 0.2
                score *= 0.8
            else:
                score = float(counts.get(simple, 0))
                if simple in GENERIC_NAMES:
                    score *= 0.1
            if simple.startswith("_"):
                score *= 0.25
            if symbol["kind"] == "class":
                score *= 1.5
            elif len(simple) <= 2:
                score *= 0.1
            if is_support_path(symbol["path"]):
                score *= 0.25
            scores.append(score)
        return scores

    def _cache_path(self, fingerprint: str) -> Path:
        key = hashlib.sha1(f"{self.root}\0{fingerprint}\0{CACHE_VERSION}".encode()).hexdigest()
        return self._cache_dir / f"index-{key}.json.gz"

    def _load_cache(self, fingerprint: str) -> bool:
        path = self._cache_path(fingerprint)
        try:
            with gzip.open(str(path), "rt", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError, TypeError, EOFError):
            return False
        if not isinstance(data, dict):
            return False
        if (
            data.get("version") != CACHE_VERSION
            or data.get("root") != str(self.root)
            or data.get("fingerprint") != fingerprint
        ):
            return False
        try:
            symbols = data["symbols"]
            variables = data["variables"]
            documents = data["documents"]
            lengths = data["lengths"]
            importance = data["importance"]
            if not (isinstance(symbols, list) and len(symbols) == len(documents) == len(lengths) == len(importance)):
                return False
            self.symbols = symbols
            self.variables = variables
            self.skipped = data["skipped"]
            self.file_count = int(data["file_count"])
            self.documents = [Counter(document) for document in documents]
            self.lengths = [int(length) for length in lengths]
            self.average_length = float(data["average_length"])
            self.document_frequency = Counter(data["document_frequency"])
            self.file_document_frequency = Counter(data["file_document_frequency"])
            self.file_average_length = float(data["file_average_length"])
            self.symbol_count = int(data["symbol_count"])
            self.symbol_document_frequency = Counter(data["symbol_document_frequency"])
            self.symbol_average_length = float(data["symbol_average_length"])
            self.importance = [float(value) for value in importance]
        except (KeyError, TypeError, ValueError):
            return False
        for entry in self.symbols:
            entry["source"] = ""
        for entry in self.variables:
            entry["source"] = ""
        return True

    def _save_cache(self, fingerprint: str) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        data = {
            "version": CACHE_VERSION,
            "root": str(self.root),
            "fingerprint": fingerprint,
            "file_count": self.file_count,
            "skipped": self.skipped,
            "symbols": [{k: v for k, v in symbol.items() if k != "source"} for symbol in self.symbols],
            "variables": [{k: v for k, v in variable.items() if k != "source"} for variable in self.variables],
            "documents": [dict(document) for document in self.documents],
            "lengths": self.lengths,
            "average_length": self.average_length,
            "document_frequency": dict(self.document_frequency),
            "file_document_frequency": dict(self.file_document_frequency),
            "file_average_length": self.file_average_length,
            "symbol_count": self.symbol_count,
            "symbol_document_frequency": dict(self.symbol_document_frequency),
            "symbol_average_length": self.symbol_average_length,
            "importance": self.importance,
        }
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("wb", dir=str(self._cache_dir), prefix=".index-", delete=False) as handle:
                temporary = handle.name
            with gzip.open(temporary, "wt", encoding="utf-8", compresslevel=3) as handle:
                json.dump(data, handle, separators=(",", ":"))
            os.replace(temporary, str(self._cache_path(fingerprint)))
        except (OSError, TypeError, ValueError):
            if temporary and Path(temporary).exists():
                try:
                    os.unlink(temporary)
                except OSError:
                    pass

    def search(self, query: str, limit: int = 10, file_only: bool = False) -> "list[dict]":
        query_terms = set(terms(query))
        ranked = []
        if file_only:
            document_frequency = self.file_document_frequency
            document_count = self.file_count
            average_length = self.file_average_length
        else:
            document_frequency = self.symbol_document_frequency
            document_count = self.symbol_count
            average_length = self.symbol_average_length
        for symbol, document, length in zip(self.symbols, self.documents, self.lengths):
            if file_only:
                if symbol["kind"] != "module":
                    continue
            elif symbol["kind"] == "module":
                continue
            score = 0.0
            for term in query_terms & document.keys():
                frequency = document[term]
                idf = math.log(1 + (document_count - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
                score += idf * frequency * 2.5 / (frequency + 1.5 * (0.25 + 0.75 * length / max(1.0, average_length)))
            if symbol["kind"] != "module":
                score += 2 * len(query_terms & set(terms(symbol["name"])))
            if score > 0:
                ranked.append({**{k: v for k, v in symbol.items() if k != "source"}, "score": round(score, 6)})
        return sorted(ranked, key=lambda s: (-s["score"], s["path"], s["start_line"], s["name"]))[:limit]

    def ranked_files(self, query: str, file_only: bool = False) -> "list[str]":
        return list(dict.fromkeys(symbol["path"] for symbol in self.search(query, len(self.symbols), file_only)))

    def find(self, symbol: str, symbol_type: str = "any", limit: "int | None" = None) -> "list[dict]":
        """Return exact symbol definitions, optionally filtered by kind."""
        if symbol_type not in {"any", "function", "class", "variable"}:
            raise ValueError("symbol_type must be one of: any, function, class, variable")
        if limit is not None and (not isinstance(limit, int) or limit < 1):
            raise ValueError("limit must be a positive integer")
        if not symbol:
            return []
        matches = []
        for entry in self.symbols + self.variables:
            if entry["kind"] == "module":
                continue
            if symbol_type == "function" and entry["kind"] not in {"function", "method"}:
                continue
            if symbol_type == "class" and entry["kind"] != "class":
                continue
            if symbol_type == "variable" and entry["kind"] != "variable":
                continue
            name = entry["name"]
            if name != symbol and name.rsplit(".", 1)[-1] != symbol:
                continue
            matches.append(entry)
        matches.sort(
            key=lambda entry: (
                0 if entry["kind"] != "variable" else 1,
                0 if entry["name"] == symbol else 1,
                entry["path"],
                entry["start_line"],
                entry["name"],
            )
        )
        return matches[:limit] if limit is not None else matches

    def repo_map(self, query: str, max_chars: int = 6000) -> str:
        if query.strip():
            candidates = [
                {k: v for k, v in symbol.items() if k != "source"} for symbol in self.search(query, len(self.symbols))
            ]
        else:
            ranked = sorted(
                (
                    (self.importance[index], symbol)
                    for index, symbol in enumerate(self.symbols)
                    if symbol["kind"] != "module" and not is_support_path(symbol["path"])
                ),
                key=lambda item: (-item[0], item[1]["path"], item[1]["start_line"], item[1]["name"]),
            )
            candidates = [{k: v for k, v in symbol.items() if k != "source"} for _, symbol in ranked]
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

    def _entry_source(self, symbol: dict) -> str:
        """Return symbol source, reading it from disk for cache-loaded entries."""
        source = symbol.get("source") or ""
        if source:
            return source
        try:
            text = (self.root / symbol["path"]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return symbol.get("signature", "")
        lines = text.splitlines()
        return "\n".join(lines[symbol["start_line"] - 1 : symbol["end_line"]])

    def _class_header(self, symbol: dict) -> str:
        if symbol["kind"] != "method":
            return ""
        owner = symbol["name"].rsplit(".", 1)[0]
        for candidate in self.symbols:
            if candidate["kind"] == "class" and candidate["path"] == symbol["path"] and candidate["name"] == owner:
                return candidate["signature"]
        return ""

    def _context_selection(self, query: str, max_files: int = 5) -> "list[dict]":
        """Select files and symbols for the context builder and offline eval."""
        if not isinstance(max_files, int) or max_files < 1:
            max_files = 5
        if query.strip():
            file_hits = self.search(query, limit=len(self.symbols), file_only=True)
            symbol_hits = self.search(query, limit=50)
        else:
            file_hits = []
            ranked = sorted(
                (
                    (self.importance[index], symbol)
                    for index, symbol in enumerate(self.symbols)
                    if symbol["kind"] != "module"
                ),
                key=lambda item: (-item[0], item[1]["path"], item[1]["start_line"], item[1]["name"]),
            )
            symbol_hits = [
                {**{k: v for k, v in symbol.items() if k != "source"}, "score": score} for score, symbol in ranked[:50]
            ]
        candidates = {}
        for rank, hit in enumerate(file_hits):
            path = hit["path"]
            entry = candidates.setdefault(path, {"path": path, "symbols": [], "file_score": 0.0, "file_rank": rank})
            entry["file_score"] = max(entry["file_score"], hit["score"])
        for rank, hit in enumerate(symbol_hits):
            path = hit["path"]
            entry = candidates.setdefault(path, {"path": path, "symbols": [], "file_score": 0.0, "file_rank": 10**6})
            entry["symbols"].append((rank, hit))
        if not candidates:
            return []

        def order_key(item):
            entry = item[1]
            best_symbol = min((rank for rank, _ in entry["symbols"]), default=10**6)
            fused = 0.0
            if entry["file_rank"] < 10**6:
                fused += 1.0 / (60 + entry["file_rank"] + 1)
            if best_symbol < 10**6:
                fused += 1.0 / (60 + best_symbol + 1)
            return (is_support_path(entry["path"]), -fused, entry["path"])

        selected = []
        support_files = 0
        for entry in (item[1] for item in sorted(candidates.items(), key=order_key)):
            if is_support_path(entry["path"]):
                if support_files >= 1:
                    continue
                support_files += 1
            if not entry["symbols"]:
                fallback = [
                    symbol
                    for symbol in self.symbols
                    if symbol["path"] == entry["path"] and symbol["kind"] in {"class", "function", "method"}
                ]
                fallback.sort(key=lambda symbol: (symbol["start_line"], symbol["name"]))
                if fallback:
                    entry["symbols"] = [
                        (
                            10**6,
                            {**{k: v for k, v in fallback[0].items() if k != "source"}, "score": entry["file_score"]},
                        )
                    ]
            if entry["symbols"]:
                selected.append(entry)
            if len(selected) >= max_files:
                break

        for entry in selected:
            ranked_symbols = sorted(entry["symbols"], key=lambda item: item[0])[:3]
            kept = []
            for _, symbol in ranked_symbols:
                # Keep the most specific definition: drop a class/function when
                # it contains another selected symbol (usually one of its methods).
                if any(
                    other is not symbol
                    and symbol["start_line"] <= other["start_line"]
                    and symbol["end_line"] >= other["end_line"]
                    and (symbol["start_line"], symbol["end_line"]) != (other["start_line"], other["end_line"])
                    for _, other in ranked_symbols
                ):
                    continue
                kept.append(symbol)
            entry["symbols"] = kept[:1] if kept else ([ranked_symbols[0][1]] if ranked_symbols else [])
        return selected

    def context_files(self, query: str, max_files: int = 5) -> "list[str]":
        """Ordered file paths selected by the context builder (used by offline eval)."""
        return [entry["path"] for entry in self._context_selection(query, max_files)]

    def build_context(
        self,
        query: str,
        max_chars: int = 6000,
        max_files: int = 5,
        snippet_lines: int = 8,
    ) -> str:
        """Return a compact, budgeted context block with signatures and snippets."""
        selected = self._context_selection(query, max_files)
        clean_query = " ".join(query.split())[:200]
        header = "Code context for: %s\nRanked by BM25 file/symbol fusion; snippets are excerpts.\n" % (
            clean_query or "(structural overview)"
        )
        if not selected:
            return (header + "No matching Python symbols.\n")[:max_chars]
        raw_scores = [symbol.get("score", 0.0) for entry in selected for symbol in entry["symbols"]]
        max_score = max(raw_scores) if raw_scores else 1.0
        marker = "\n[context truncated to character budget]\n"
        output = header
        omitted = False
        for entry in selected:
            block_lines = [entry["path"]]
            for symbol in entry["symbols"]:
                score = (symbol.get("score", 0.0) / max_score) if max_score else 0.0
                block_lines.append(
                    f"  {symbol['name']}  lines {symbol['start_line']}-{symbol['end_line']}  [score {score:.2f}]"
                )
                class_header = self._class_header(symbol)
                if class_header:
                    block_lines.append("  " + class_header)
                snippet = self._entry_source(symbol)
                snippet_lines_list = snippet.splitlines()
                if snippet_lines <= 0 or not snippet_lines_list:
                    block_lines.append("  " + symbol.get("signature", ""))
                    snippet_lines_list = []
                elif len(snippet_lines_list) > snippet_lines:
                    snippet_lines_list = snippet_lines_list[:snippet_lines] + ["..."]
                for line in snippet_lines_list:
                    block_lines.append("  " + line)
                block_lines.append("")
            block = "\n".join(block_lines).rstrip()
            remaining = max_chars - len(marker) - len(output) - 2
            if remaining <= 0:
                omitted = True
                break
            if len(block) > remaining:
                block = block[: max(0, remaining - 3)].rstrip() + "..."
                omitted = True
            output += "\n" + block + "\n"
            if omitted:
                break
        if omitted:
            output += marker
        return output[:max_chars]


def _definition_context(path: Path, start_line: int, context_lines: int, fallback: str) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return fallback
    index = start_line - 1
    start = max(0, index - context_lines)
    end = min(len(lines), index + context_lines + 1)
    parts = []
    for position in range(start, end):
        marker = ">>>" if position == index else "   "
        parts.append(f"{marker} {position + 1:4d}: {lines[position]}")
    return "\n".join(parts) or fallback


def find_definition(
    root: str = ".",
    symbol: str = "",
    symbol_type: str = "any",
    path: str = ".",
    context_lines: int = 5,
    limit: int = 10,
) -> dict:
    """Locate exact Python definitions and return readable line context."""
    if not isinstance(symbol, str) or not symbol:
        return {"output": "Missing 'symbol' parameter", "returncode": 2}
    if symbol_type not in {"any", "function", "class", "variable"}:
        return {"output": "symbol_type must be one of: any, function, class, variable", "returncode": 2}
    if not isinstance(context_lines, int) or context_lines < 0:
        return {"output": "context_lines must be a non-negative integer", "returncode": 2}
    if not isinstance(limit, int) or not 1 <= limit <= 50:
        return {"output": "limit must be between 1 and 50", "returncode": 2}
    if not path:
        path = "."
    root_path = Path(root).expanduser().resolve()
    target = Path(path).expanduser()
    target = target.resolve() if target.is_absolute() else (root_path / target).resolve()
    if not target.exists():
        return {"output": f"Path not found: {path}", "returncode": 2}
    index_root = target if target.is_dir() else target.parent
    try:
        index = RepositoryIndex(index_root)
        matches = index.find(symbol, symbol_type)
    except (OSError, ValueError) as exc:
        return {"output": f"Error finding definition: {exc}", "returncode": 1}
    if target.is_file():
        matches = [entry for entry in matches if (index_root / entry["path"]).resolve() == target]
    if not matches:
        return {"output": f"No definition found for '{symbol}' (type: {symbol_type}) in {path}", "returncode": 0}
    output_lines = [f"Found {len(matches)} definition(s) for '{symbol}':\n"]
    for entry in matches[:limit]:
        full_path = (index_root / entry["path"]).resolve()
        try:
            display_path = full_path.relative_to(root_path).as_posix()
        except ValueError:
            display_path = str(full_path)
        output_lines.append(f"{display_path}:{entry['start_line']}: {entry['kind']} {entry['name']}")
        output_lines.append(
            _definition_context(full_path, entry["start_line"], context_lines, entry.get("signature", ""))
        )
    if len(matches) > limit:
        output_lines.append(f"\n... and {len(matches) - limit} more result(s)")
    return {"output": "\n".join(output_lines), "returncode": 0}


def retrieve(args: dict) -> dict:
    operation = args.get("operation")
    if operation not in {"code_search", "repo_map", "context"}:
        return {"output": f"Unknown retrieval operation: {operation}", "returncode": 2}
    query = args.get("query", "")
    if operation in {"code_search", "context"} and (not isinstance(query, str) or not query.strip()):
        return {"output": "query must be a nonempty string", "returncode": 2}
    index = RepositoryIndex(Path(args.get("root", ".")))
    if operation == "repo_map":
        return {
            "output": index.repo_map(query if isinstance(query, str) else "", args.get("max_chars", 6000)),
            "returncode": 0,
        }
    if operation == "context":
        return {
            "output": index.build_context(
                query,
                args.get("max_chars", 6000),
                args.get("max_files", 5),
                args.get("snippet_lines", 8),
            ),
            "returncode": 0,
        }
    return {
        "output": json.dumps(
            {
                "matches": index.search(query, args.get("limit", 10)),
                "files_indexed": index.file_count,
                "skipped": index.skipped,
            }
        ),
        "returncode": 0,
    }
