"""Offline file localization evaluation; gold files never enter retrieval queries."""

import json
import time
from pathlib import Path

import typer

from minisweagent.retrieval.repository import RepositoryIndex

app = typer.Typer(add_completion=False)


def evaluate(cases: list[dict], base_dir: Path, k: int = 5) -> dict:
    if k < 1 or not cases:
        raise ValueError("Provide at least one case and a positive k.")
    indexes = {}
    rows = []
    for case in cases:
        root = (base_dir / case["repo"]).resolve()
        if root not in indexes:
            indexes[root] = RepositoryIndex(root)
        gold = set(case["gold_files"])
        if not gold:
            raise ValueError(f"No gold files for {case['instance_id']}")
        for method, file_only in (("file_bm25", True), ("symbol_bm25", False)):
            start = time.perf_counter()
            ranking = indexes[root].ranked_files(case["issue"], file_only=file_only)
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
        "methods": {
            method: {
                metric: sum(row[metric] for row in rows if row["method"] == method) / len(cases)
                for metric in ("recall_at_k", "hit_at_k", "reciprocal_rank")
            }
            for method in ("file_bm25", "symbol_bm25")
        },
        "index_stats": {
            str(root): {"files": index.file_count, "skipped": index.skipped} for root, index in indexes.items()
        },
        "tasks": rows,
    }


@app.command()
def main(
    cases: Path = typer.Option(..., exists=True, dir_okay=False),
    output: Path = typer.Option(...),
    k: int = typer.Option(5, min=1),
) -> None:
    result = evaluate(json.loads(cases.read_text()), cases.parent, k)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    typer.echo(json.dumps(result["methods"], indent=2))


if __name__ == "__main__":
    app()
