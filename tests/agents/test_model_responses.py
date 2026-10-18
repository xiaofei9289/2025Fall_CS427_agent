"""Provider failures must not execute actions or consume an entire run in a loop."""

from unittest.mock import Mock

import pytest

from minisweagent.agents.default import DefaultAgent


def make_agent(responses, **config):
    model = Mock(cost=0.0, n_calls=0)
    model.get_template_vars.return_value = {}
    pending = iter(responses)

    def query(_messages):
        response = next(pending)
        model.n_calls += 1
        model.cost += 0.1
        return response

    model.query.side_effect = query
    env = Mock()
    env.get_template_vars.return_value = {}
    env.execute.return_value = {"output": "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\ndone", "returncode": 0}
    return DefaultAgent(model, env, cost_limit=10, **config)


def test_consecutive_empty_responses_stop_before_step_budget():
    agent = make_agent([{"content": ""} for _ in range(3)], step_limit=50)
    status, message = agent.run("fix bug")
    assert status == "ModelResponseError"
    assert "3 consecutive" in message
    assert agent.model.n_calls == 3
    assert agent.model.cost == pytest.approx(0.3)
    agent.env.execute.assert_not_called()
    assert not any("Please always provide EXACTLY ONE action" in m["content"] for m in agent.messages)


@pytest.mark.parametrize(("status", "count"), [("filtered", 1), ("truncated", 3)])
def test_filtered_or_truncated_content_is_never_executed(status, count):
    response = {"content": "```bash\necho must_not_execute\n```", "extra": {"response_status": status}}
    agent = make_agent([response.copy() for _ in range(count)])
    exit_status, _ = agent.run("fix bug")
    assert exit_status == "ModelResponseError"
    assert agent.model.n_calls == count
    agent.env.execute.assert_not_called()


def test_valid_action_resets_empty_response_streak():
    action = {"content": "```bash\necho progress\n```"}
    agent = make_agent([{"content": ""}, action, {"content": ""}, {"content": ""}, action])
    agent.env.execute.side_effect = [
        {"output": "progress", "returncode": 0},
        {"output": "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\ndone", "returncode": 0},
    ]
    assert agent.run("fix bug") == ("Submitted", "done")
    assert agent.model.n_calls == 5
    assert agent.env.execute.call_count == 2


def test_empty_response_streak_survives_loaded_session(tmp_path):
    from minisweagent.memory import SessionMemory

    SessionMemory(tmp_path, "retry").save_session([
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": ""},
        {"role": "user", "content": "empty response"},
        {"role": "assistant", "content": ""},
        {"role": "user", "content": "empty response"},
    ])
    agent = make_agent([{"content": ""}], enable_memory=True, memory_load_session=True,
                       memory_dir=str(tmp_path), memory_session_id="retry")
    assert agent.run("continue")[0] == "ModelResponseError"
    assert agent.model.n_calls == 1


def test_empty_responses_still_obey_hard_step_limit():
    agent = make_agent([{"content": ""}], step_limit=1)
    assert agent.run("fix bug")[0] == "LimitsExceeded"
    assert agent.model.n_calls == 1


def test_empty_assistant_turn_is_audited_but_not_sent_again():
    agent = make_agent([{"content": ""}, {"content": "```bash\necho finish\n```"}])
    assert agent.run("fix bug")[0] == "Submitted"
    assert any(m["role"] == "assistant" and m["content"] == "" for m in agent.messages)
    sent = agent.model.query.call_args_list[1].args[0]
    assert not any(m["role"] == "assistant" and not m["content"].strip() for m in sent)
