# Recorded test fixtures

`github_issue.traj.json` is restored unchanged from
[mini-swe-agent v1.11.1](https://github.com/SWE-agent/mini-swe-agent/blob/v1.11.1/tests/test_data/github_issue.traj.json),
the upstream version used by this project. It records the public
`SWE-agent/test-repo` missing-colon task. Tests replay its model responses in a
real execution environment and compare the resulting patch with the recorded
submission; they do not call a model API.
