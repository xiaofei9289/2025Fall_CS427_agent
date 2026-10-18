"""Offline replay of saved trajectories through history compression.

For every model call in a trajectory, recompute what ``HistoryManager`` would
have sent and classify each earlier file read as fully visible, excerpted in
the ``[memory]`` summary, or lost. No model or environment is involved.
"""

import json
import re
from pathlib import Path
from typing import Any

import typer

from minisweagent.memory.history import _FILE_READ_RE, HistoryManager, message_text

app = typer.Typer(add_completion=False)

_RETURN_RE = re.compile(r"<returncode>(-?\d+)</returncode>")


def read_events(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Successful file reads with the step number used by the evidence note."""
    events = []
    step = 0
    for index, message in enumerate(messages[:-1]):
        if message.get("role") != "assistant":
            continue
        step += 1
        observation = messages[index + 1]
        action = HistoryManager()._action(message)
        if action is None or observation.get("role") != "user":
            continue
        text = message_text(observation)
        code = observation.get("extra", {}).get("returncode")
        if code is None:
            match = _RETURN_RE.search(text)
            code = int(match.group(1)) if match else None
        if code != 0:
            continue
        kind, name, args = action
        if kind == "tool" and name in {"read_file", "refined_read_file"}:
            events.append({"step": step, "index": index, "label": f"{name} {args.get('path', '')}", "text": text})
        elif kind == "bash" and _FILE_READ_RE.search(args["command"]):
            events.append({"step": step, "index": index, "label": args["command"][:160], "text": text})
    return events


def sent_messages(history: HistoryManager, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mirror the agent: compress, fall back to the full transcript on ValueError."""
    try:
        sent = history.prompt_messages(messages)
    except ValueError:
        sent = messages
    return [m for m in sent if not (m.get("role") == "assistant" and not (m.get("content") or "").strip())]


def classify(event: dict[str, Any], sent_texts: list[str], blob: str) -> str:
    if any(text == event["text"] for text in sent_texts):
        return "full"
    if f"step {event['step']}:" in blob:
        return "excerpt"
    return "lost"


def replay(messages: list[dict[str, Any]], max_messages: int) -> dict[str, Any]:
    history = HistoryManager(max_messages=max_messages)
    events = read_events(messages)
    calls = []
    for index, message in enumerate(messages):
        if message.get("role") != "assistant":
            continue
        sent = sent_messages(history, messages[:index])
        sent_texts = [message_text(m) for m in sent]
        blob = "\n".join(sent_texts)
        past = [event for event in events if event["index"] + 1 < index]
        states = [classify(event, sent_texts, blob) for event in past]
        calls.append(
            {
                "call": len(calls) + 1,
                "full_messages": index,
                "sent_messages": len(sent),
                "compressed": len(sent) < index,
                "reads": {state: states.count(state) for state in ("full", "excerpt", "lost")},
                "latest_read": states[-1] if states else None,
            }
        )
    latest = [call["latest_read"] for call in calls]
    total_reads = sum(call["reads"]["full"] + call["reads"]["excerpt"] + call["reads"]["lost"] for call in calls)
    return {
        "max_messages": max_messages,
        "model_calls": len(calls),
        "read_events": len(events),
        "compressed_calls": sum(call["compressed"] for call in calls),
        "latest_read_not_full": sum(state in ("excerpt", "lost", None) and state is not None for state in latest),
        "latest_read_lost": sum(state == "lost" for state in latest),
        "reads_full_ratio": (
            sum(call["reads"]["full"] for call in calls) / total_reads if total_reads else 1.0
        ),
        "calls": calls,
    }


@app.command()
def main(
    trajectory: Path = typer.Option(..., exists=True, dir_okay=False),
    output: Path = typer.Option(None),
    memory_max: list[int] = typer.Option([12, 24, 40], help="Message budget to replay; repeatable"),
) -> None:
    data = json.loads(trajectory.read_text())
    messages = data["messages"]
    thresholds = {limit: replay(messages, limit) for limit in sorted(set(memory_max))}
    report = {
        "trajectory": str(trajectory),
        "instance_id": data.get("instance_id"),
        "exit_status": data.get("info", {}).get("exit_status"),
        "total_messages": len(messages),
        "thresholds": thresholds,
    }
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n")
    for limit, result in thresholds.items():
        typer.echo(
            f"max_messages={limit}: calls={result['model_calls']} reads={result['read_events']} "
            f"compressed={result['compressed_calls']} latest_read_not_full={result['latest_read_not_full']} "
            f"latest_read_lost={result['latest_read_lost']} reads_full_ratio={result['reads_full_ratio']:.3f}"
        )


if __name__ == "__main__":
    app()
