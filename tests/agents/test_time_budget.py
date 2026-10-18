import pytest

from minisweagent.agents.default import DefaultAgent
from minisweagent.environments.local import LocalEnvironment
from minisweagent.models.test_models import DeterministicModel


@pytest.mark.parametrize(("seconds", "status", "calls"), [(1e-9, "LimitsExceeded", 0), (0, "Submitted", 1)])
def test_wall_time_budget_before_model_call(seconds, status, calls):
    model = DeterministicModel(outputs=["```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n```"])
    agent = DefaultAgent(model, LocalEnvironment(), time_limit=seconds)
    assert agent.run("Finish")[0] == status
    assert model.n_calls == calls
