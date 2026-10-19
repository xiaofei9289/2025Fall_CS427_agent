import subprocess

import pytest

from minisweagent.environments.docker import DockerEnvironment
from minisweagent.tools.code_search import CodeContextTool
from minisweagent.tools.find_references import FindReferencesTool


def docker_available() -> bool:
    try:
        subprocess.run(["docker", "version"], capture_output=True, check=True, timeout=10)
        return True
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


@pytest.mark.slow
@pytest.mark.skipif(not docker_available(), reason="Docker not available")
def test_context_and_references_inside_container():
    """The SWE-bench path: run the embedded index in a container without git."""
    env = DockerEnvironment(image="python:3.11", cwd="/", timeout=60)
    try:
        source = '''class Session:
    async def refresh_token(self, token):
        """Refresh a token."""
        return token

def login(user):
    return Session().refresh_token(user)
'''
        command = "mkdir -p /testbed/src && cat > /testbed/src/auth.py <<'PY'\n" + source + "PY\n"
        written = env.execute(command)
        assert written["returncode"] == 0, written["output"]

        env.config.cwd = "/testbed"
        context = CodeContextTool()({"query": "refresh_token", "max_chars": 2000}, env)
        assert context["returncode"] == 0, context["output"]
        assert "src/auth.py" in context["output"]
        assert "refresh_token" in context["output"]

        references = FindReferencesTool()({"symbol": "refresh_token", "path": ".", "context_lines": 1}, env)
        assert references["returncode"] == 0, references["output"]
        assert "Definitions for 'Session.refresh_token'" in references["output"]
        assert "src/auth.py" in references["output"]
    finally:
        env.cleanup()
