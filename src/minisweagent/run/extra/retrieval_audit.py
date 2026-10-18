"""Per-task retrieval attribution for saved trajectories.

The audit answers a narrower question than "did the run pass": for each task,
did the first retrieval find a gold file, did the agent read it, and did it edit
it?  This separates a retrieval miss from a planning/editing/test failure.

Example:
    python -m minisweagent.run.extra.retrieval_audit \
      --run-dir experiments/gate-20261017/retrieval \
      --cases experiments/localization_verified5/cases.json \
      --grading experiments/gate-20261017/retrieval/evaluation/grading_summary.json \
      --output experiments/gate-20261017/retrieval_audit.json
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import typer

app = typer.Typer(add_completion=False)

_TOOL_RE = re.compile(r"```tool\n(.*?)\n```", re.DOTALL)
_BASH_RE = re.compile(r"```bash\n(.*?)\n```", re.DOTALL)
_PATH_RE = re.compile(r"(?<![\w/.-])((?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.py)")
_DIFF_RE = re.compile(r"^diff --git a/(\S+) b/(\S+)", re.MULTILINE)
_SEARCH_TOOLS = {"code_search", "repo_map", "code_context"}
_READ_TOOLS = {"read_file", "refined_read_file", "read_many_files"}
_BASH_READ = re.compile(r"\b(cat|sed|head|tail|grep|nl|awk)\b")


def _messages(trajectory: dict) -> list[dict]:
    messages = trajectory.get("messages", [])
    return messages if isinstance(messages, list) else []


def _observation(messages: list[dict], index: int) -> str:
    if index + 1 < len(messages) and messages[index + 1].get("role") == "user":
        return str(messages[index + 1].get("content", ""))
    return ""


def _iter_actions(messages: list[dict]):
    for index, message in enumerate(messages):
        if message.get("role") != "assistant":
            continue
        content = str(message.get("content", ""))
        observation = _observation(messages, index)
        for block in _TOOL_RE.findall(content):
            try:
                payload = json.loads(block)
            except (TypeError, ValueError):
                continue
            if not isinstance(payload, dict) or not isinstance(payload.get("name"), str):
                continue
            args = payload.get("args", {})
            yield index, payload["name"], args if isinstance(args, dict) else {}, observation
        for block in _BASH_RE.findall(content):
            yield index, "bash", {"command": block.strip()}, observation


def _json_payload(text: str) -> dict:
    body = text
    if "<output>" in body and "</output>" in body:
        body = body.split("<output>", 1)[1].rsplit("</output>", 1)[0]
    body = body.strip()
    try:
        value = json.loads(body)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _paths_from_text(text: str) -> list[str]:
    paths = []
    for match in _PATH_RE.finditer(text):
        path = match.group(1).lstrip("./")
        if path and path not in paths:
            paths.append(path)
    return paths


def _search_result_paths(name: str, observation: str) -> list[str]:
    if name == "code_search":
        payload = _json_payload(observation)
        matches = payload.get("matches", [])
        if isinstance(matches, list):
            paths = []
            for match in matches:
                if isinstance(match, dict) and isinstance(match.get("path"), str):
                    path = match["path"]
                    if path not in paths:
                        paths.append(path)
            if paths:
                return paths
    return _paths_from_text(observation)


def _read_paths(name: str, args: dict, command: str) -> list[str]:
    if name in _READ_TOOLS:
        values = args.get("paths") if name == "read_many_files" else [args.get("path")]
        if not isinstance(values, list):
            values = [values]
        return [value for value in values if isinstance(value, str) and value]
    if name == "bash" and _BASH_READ.search(command or ""):
        return _paths_from_text(command)
    return []


def _submission_paths(trajectory: dict) -> list[str]:
    info = trajectory.get("info") or {}
    submission = str(info.get("submission", "") or "") if isinstance(info, dict) else ""
    paths = []
    for match in _DIFF_RE.finditer(submission):
        path = match.group(1)
        if path not in paths:
            paths.append(path)
    return paths


def _load_cases(path: Path | None) -> dict[str, set[str]]:
    if path is None:
        return {}
    data = json.loads(path.read_text())
    cases = {}
    if isinstance(data, list):
        for case in data:
            if isinstance(case, dict) and case.get("instance_id"):
                cases[str(case["instance_id"])] = set(case.get("gold_files", []))
    return cases


def _load_grading(path: Path | None) -> tuple[set[str], set[str]]:
    if path is None:
        return set(), set()
    data = json.loads(path.read_text())
    resolved = set(data.get("resolved_ids", [])) if isinstance(data, dict) else set()
    errors = set(data.get("error_ids", [])) if isinstance(data, dict) else set()
    return resolved, errors


def _first_search(actions: list[tuple[int, str, dict, str]]) -> tuple[int, str, dict, str] | None:
    for action in actions:
        if action[1] in _SEARCH_TOOLS:
            return action
    return None


def classify(
    *,
    resolved: bool | None,
    first_search: tuple[int, str, dict, str] | None,
    gold_rank: int | None,
    read_gold: bool,
    edited_gold: bool,
    has_gold: bool,
) -> str:
    if not has_gold:
        return "no_gold"
    if first_search is None:
        return "no_search"
    if gold_rank is None:
        return "retrieval_miss"
    if not read_gold:
        return "retrieved_not_read"
    if not edited_gold:
        return "read_not_edited"
    if resolved is True:
        return "resolved"
    if resolved is None:
        return "edited_outcome_unknown"
    return "edited_not_resolved"


def audit_trajectory(
    trajectory: dict,
    *,
    gold_files: set[str],
    resolved: bool | None,
    k: int = 10,
) -> dict[str, Any]:
    messages = _messages(trajectory)
    actions = list(_iter_actions(messages))
    first = _first_search(actions)
    first_query = ""
    top_paths: list[str] = []
    if first is not None:
        first_query = str(first[2].get("query", ""))
        top_paths = _search_result_paths(first[1], first[3])
    gold_rank = next((index + 1 for index, path in enumerate(top_paths) if path in gold_files), None)
    search_calls = sum(1 for action in actions if action[1] in _SEARCH_TOOLS)

    all_reads = []
    read_after = []
    for index, name, args, _observation_text in actions:
        paths = _read_paths(name, args, str(args.get("command", "")))
        all_reads.extend(paths)
        if first is not None and index > first[0]:
            read_after.extend(paths)
    read_gold = bool(gold_files & set(all_reads))
    read_after_gold = bool(gold_files & set(read_after))
    submission_paths = _submission_paths(trajectory)
    edited_gold = bool(gold_files & set(submission_paths))
    info = trajectory.get("info") or {}
    stats = info.get("model_stats") or {}
    if not isinstance(stats, dict):
        stats = {}
    status = info.get("exit_status", "")
    return {
        "instance_id": trajectory.get("instance_id", ""),
        "exit_status": status,
        "resolved": resolved,
        "steps": sum(1 for message in messages if message.get("role") == "assistant"),
        "api_calls": stats.get("api_calls"),
        "cost": stats.get("instance_cost"),
        "first_search_tool": first[1] if first else "",
        "first_search_query": first_query,
        "search_calls": search_calls,
        "top_paths": top_paths[:k],
        "gold_rank": gold_rank,
        "gold_in_top_k": gold_rank is not None and gold_rank <= k,
        "read_after_search": read_after[:20],
        "read_after_search_gold": read_after_gold,
        "read_gold": read_gold,
        "edited_paths": submission_paths[:20],
        "edited_gold": edited_gold,
        "classification": classify(
            resolved=resolved,
            first_search=first,
            gold_rank=gold_rank,
            read_gold=read_gold,
            edited_gold=edited_gold,
            has_gold=bool(gold_files),
        ),
    }


def audit(
    run_dir: Path,
    *,
    cases_path: Path | None = None,
    grading_path: Path | None = None,
    k: int = 10,
) -> dict[str, Any]:
    cases = _load_cases(cases_path)
    resolved, errors = _load_grading(grading_path)
    tasks = []
    for path in sorted(run_dir.rglob("*.traj.json")):
        try:
            trajectory = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        instance_id = str(trajectory.get("instance_id", path.parent.name))
        outcome = True if instance_id in resolved else (None if not resolved else False)
        tasks.append(
            audit_trajectory(
                trajectory,
                gold_files=cases.get(instance_id, set()),
                resolved=outcome,
                k=k,
            )
        )
    counts: dict[str, int] = {}
    for task in tasks:
        classification = task["classification"]
        counts[classification] = counts.get(classification, 0) + 1
    return {
        "run_dir": str(run_dir),
        "k": k,
        "cases": len(cases),
        "grading": str(grading_path) if grading_path else "",
        "summary": {
            "tasks": len(tasks),
            "counts": counts,
            "gold_in_top_k": sum(1 for task in tasks if task["gold_in_top_k"]),
            "read_gold": sum(1 for task in tasks if task["read_gold"]),
            "edited_gold": sum(1 for task in tasks if task["edited_gold"]),
            "resolved": sum(1 for task in tasks if task["resolved"] is True),
            "errors": sorted(errors),
        },
        "tasks": tasks,
    }


def _markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Retrieval attribution audit",
        "",
        f"Run: `{result['run_dir']}`",
        f"Tasks: {result['summary']['tasks']}; gold in top-{result['k']}: "
        f"{result['summary']['gold_in_top_k']}; read gold: {result['summary']['read_gold']}; "
        f"edited gold: {result['summary']['edited_gold']}; resolved: {result['summary']['resolved']}.",
        "",
        "| Instance | Resolved | Gold rank | Read gold | Edited gold | Class | Steps | Search query |",
        "| --- | --- | ---: | --- | --- | --- | ---: | --- |",
    ]
    for task in result["tasks"]:
        query = str(task["first_search_query"]).replace("|", "\\|")[:100]
        lines.append(
            f"| {task['instance_id']} | {task['resolved']} | {task['gold_rank']} | "
            f"{task['read_gold']} | {task['edited_gold']} | `{task['classification']}` | "
            f"{task['steps']} | {query} |"
        )
    lines.extend(["", "## Classification counts", ""])
    for name, count in sorted(result["summary"]["counts"].items()):
        lines.append(f"- `{name}`: {count}")
    return "\n".join(lines) + "\n"


@app.command()
def main(
    run_dir: Path = typer.Option(..., exists=True, file_okay=False),
    cases: Path | None = typer.Option(None, exists=True, dir_okay=False),
    grading: Path | None = typer.Option(None, exists=True, dir_okay=False),
    output: Path | None = typer.Option(None, dir_okay=False),
    k: int = typer.Option(10, min=1, max=50),
) -> None:
    grading_path = grading
    if grading_path is None:
        candidate = run_dir / "evaluation" / "grading_summary.json"
        if candidate.is_file():
            grading_path = candidate
    result = audit(run_dir, cases_path=cases, grading_path=grading_path, k=k)
    output = output or run_dir / "retrieval_audit.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    output.with_suffix(".md").write_text(_markdown(result))
    typer.echo(json.dumps(result["summary"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    app()
