"""Offline file localization evaluation; gold files never enter retrieval queries."""

import json
import time
from pathlib import Path

import typer

from minisweagent.retrieval.brief import brief_files
from minisweagent.retrieval.repository import RepositoryIndex

app = typer.Typer(add_completion=False)


def evaluate(
    cases: list[dict],
    base_dir: Path,
    k: int = 5,
    checkouts_root: Path | None = None,
) -> dict:
    if k < 1 or not cases:
        raise ValueError("Provide at least one case and a positive k.")
    # Keep at most one full index alive: 50 checkouts would otherwise retain
    # tens of thousands of symbols each and exhaust memory before the run ends.
    index = None
    current_root = None
    index_stats = {}
    rows = []
    for case in cases:
        if checkouts_root is not None:
            root = (checkouts_root / case["instance_id"]).resolve()
        else:
            root = (base_dir / case["repo"]).resolve()
        if index is None or root != current_root:
            index = RepositoryIndex(root)
            current_root = root
            index_stats[str(root)] = {
                "files": index.file_count,
                "symbols": len(index.symbols),
                "skipped": index.skipped,
            }
        gold = set(case["gold_files"])
        if not gold:
            raise ValueError(f"No gold files for {case['instance_id']}")
        for method in ("file_bm25", "symbol_bm25", "context", "brief"):
            start = time.perf_counter()
            if method == "context":
                ranking = index.context_files(case["issue"], max_files=k)
            elif method == "brief":
                ranking = brief_files(index, case["issue"], max_files=k)
            else:
                ranking = index.ranked_files(case["issue"], file_only=(method == "file_bm25"))
            rank = next((index + 1 for index, path in enumerate(ranking) if path in gold), None)
            rows.append(
                {
                    "instance_id": case["instance_id"],
                    "method": method,
                    "top_files": ranking[:k],
                    "recall_at_k": len(gold & set(ranking[:k])) / len(gold),
                    "hit_at_k": bool(gold & set(ranking[:k])),
                    "reciprocal_rank": 1 / rank if rank else 0.0,
                    "search_seconds": time.perf_counter() - start,
                }
            )
    return {
        "k": k,
        "cases": len(cases),
        "checkouts_root": str(checkouts_root) if checkouts_root is not None else "",
        "methods": {
            method: {
                metric: sum(row[metric] for row in rows if row["method"] == method) / len(cases)
                for metric in ("recall_at_k", "hit_at_k", "reciprocal_rank")
            }
            for method in ("file_bm25", "symbol_bm25", "context", "brief")
        },
        "index_stats": index_stats,
        "tasks": rows,
    }


@app.command()
def main(
    cases: Path = typer.Option(..., exists=True, dir_okay=False),
    output: Path = typer.Option(...),
    k: int = typer.Option(5, min=1),
    checkouts_root: Path | None = typer.Option(
        None,
        exists=True,
        file_okay=False,
        help="Optional directory containing <instance_id> checkouts; overrides case repo paths.",
    ),
) -> None:
    result = evaluate(json.loads(cases.read_text()), cases.parent, k, checkouts_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    typer.echo(json.dumps(result["methods"], indent=2))


if __name__ == "__main__":
    app()
