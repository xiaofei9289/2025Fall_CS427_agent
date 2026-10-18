"""Tests for offline history-compression replay of saved trajectories."""

import pytest

from minisweagent.run.extra.memory_replay import classify, read_events, replay


def assistant(content: str) -> dict:
    return {"role": "assistant", "content": f"THOUGHT: inspect\n{content}"}


def read_action(path: str) -> dict:
    return assistant(f'```tool\n{{"name": "read_file", "args": {{"path": "{path}"}}}}\n```')


def bash_action(command: str) -> dict:
    return assistant(f"```bash\n{command}\n```")


def observation(text: str, code: int = 0) -> dict:
    return {"role": "user", "content": f"<returncode>{code}</returncode>\n<output>\n{text}\n</output>"}


def base_messages() -> list[dict]:
    return [{"role": "system", "content": "system"}, {"role": "user", "content": "task"}]


def test_read_events_records_only_successful_reads():
    messages = base_messages() + [
        read_action("a.py"), observation("alpha"),
        read_action("b.py"), observation("boom", code=1),
        bash_action("sed -n '1,5p' c.py"), observation("gamma"),
        assistant('```tool\n{"name": "search_file_content", "args": {"query": "x"}}\n```'), observation("hits"),
    ]
    events = read_events(messages)
    assert [(event["step"], event["label"]) for event in events] == [(1, "read_file a.py"), (3, "sed -n '1,5p' c.py")]


def test_read_events_skips_orphan_actions():
    messages = base_messages() + [read_action("a.py")]  # No observation follows.
    assert read_events(messages) == []


def test_classify_distinguishes_full_excerpt_and_lost():
    event = {"step": 3, "text": "<returncode>0</returncode>\n<output>\nkey code\n</output>"}
    assert classify(event, [event["text"], "other"], "other") == "full"
    assert classify(event, ["other"], "irrelevant\n- step 3: Read a.py\n...") == "excerpt"
    assert classify(event, ["other"], "no evidence here") == "lost"


@pytest.mark.parametrize(
    ("max_messages", "compressed_calls"),
    [(8, 4), (50, 0)],
)
def test_replay_compression_and_latest_read(max_messages, compressed_calls):
    messages = base_messages()
    for i in range(8):
        messages += [read_action(f"f{i}.py"), observation(f"code {i} " * 40)]
    result = replay(messages, max_messages)
    assert result["model_calls"] == 8
    assert result["read_events"] == 8
    assert result["compressed_calls"] == compressed_calls
    assert all(call["latest_read"] == "full" for call in result["calls"] if call["latest_read"])


def test_replay_marks_evicted_reads_not_full():
    messages = base_messages()
    for i in range(8):
        messages += [read_action(f"f{i}.py"), observation(f"code {i} " * 40)]
    result = replay(messages, 8)
    # The first read is fully visible right after it happens; older reads are later
    # demoted to evidence-note excerpts and finally dropped from the note as well.
    assert result["calls"][1]["reads"] == {"full": 1, "excerpt": 0, "lost": 0}
    assert result["calls"][-1]["reads"] == {"full": 2, "excerpt": 4, "lost": 1}
    assert result["reads_full_ratio"] < 1.0
