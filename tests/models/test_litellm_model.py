import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import litellm
import pytest

from minisweagent.models.litellm_model import LitellmModel


def test_authentication_error_enhanced_message():
    """Test that AuthenticationError gets enhanced with config set instruction."""
    model = LitellmModel(model_name="gpt-4")

    # Create a mock exception that behaves like AuthenticationError
    original_error = Mock(spec=litellm.exceptions.AuthenticationError)
    original_error.message = "Invalid API key"

    with patch("litellm.completion") as mock_completion:
        # Make completion raise the mock error
        def side_effect(*args, **kwargs):
            raise litellm.exceptions.AuthenticationError("Invalid API key", llm_provider="openai", model="gpt-4")

        mock_completion.side_effect = side_effect

        with pytest.raises(litellm.exceptions.AuthenticationError) as exc_info:
            model._query([{"role": "user", "content": "test"}])

        # Check that the error message was enhanced
        assert "You can permanently set your API key with `mini-extra config set KEY VALUE`." in str(exc_info.value)


def test_model_registry_loading():
    """Test that custom model registry is loaded and registered when provided."""
    model_costs = {
        "my-custom-model": {
            "max_tokens": 4096,
            "input_cost_per_token": 0.0001,
            "output_cost_per_token": 0.0002,
            "litellm_provider": "openai",
            "mode": "chat",
        }
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(model_costs, f)
        registry_path = f.name

    try:
        with patch("litellm.utils.register_model") as mock_register:
            _model = LitellmModel(model_name="my-custom-model", litellm_model_registry=Path(registry_path))

            # Verify register_model was called with the correct data
            mock_register.assert_called_once_with(model_costs)
    except Exception as e:
        print(e)
        raise e
    finally:
        Path(registry_path).unlink()


def test_model_registry_none():
    """Test that no registry loading occurs when litellm_model_registry is None."""
    with patch("litellm.register_model") as mock_register:
        _model = LitellmModel(model_name="gpt-4", litellm_model_registry=None)

        # Verify register_model was not called
        mock_register.assert_not_called()


def test_model_registry_not_provided():
    """Test that no registry loading occurs when litellm_model_registry is not provided."""
    with patch("litellm.register_model") as mock_register:
        _model = LitellmModel(model_name="gpt-4o")

        # Verify register_model was not called
        mock_register.assert_not_called()


@pytest.mark.parametrize(("content", "finish_reason", "status"), [
    (None, "stop", "empty"),
    ("  ", "stop", "empty"),
    (None, "content_filter", "truncated"),
    ("```bash\necho hello\n```", "content_filter", "truncated"),
    ("```bash\necho hello\n```", "length", "truncated"),
    ("```bash\necho hello\n```", "stop", "ok"),
])
def test_response_status_preserves_accounting(content, finish_reason, status, monkeypatch, reset_global_stats):
    model = LitellmModel(model_name="gpt-4o")
    response = litellm.ModelResponse(choices=[{
        "index": 0, "finish_reason": finish_reason,
        "message": {"role": "assistant", "content": content, "reasoning_content": "internal reasoning"},
    }])
    monkeypatch.setattr(model, "_query", Mock(return_value=response))
    monkeypatch.setattr(litellm.cost_calculator, "completion_cost", Mock(return_value=0.1))
    result = model.query([{"role": "user", "content": "task"}])
    assert result["content"] == (content or "")
    assert result["extra"]["response_status"] == status
    assert result["extra"]["response"]["choices"][0]["finish_reason"] == finish_reason
    assert model.n_calls == 1
    assert model.cost == pytest.approx(0.1)


def test_refused_content_filter_is_filtered(monkeypatch, reset_global_stats):
    """An explicit provider refusal must still stop the agent immediately."""
    model = LitellmModel(model_name="gpt-4o")
    response = litellm.ModelResponse(choices=[{
        "index": 0, "finish_reason": "content_filter",
        "message": {"role": "assistant", "content": "blocked", "refusal": "policy violation"},
    }])
    monkeypatch.setattr(model, "_query", Mock(return_value=response))
    monkeypatch.setattr(litellm.cost_calculator, "completion_cost", Mock(return_value=0.1))
    assert model.query([{"role": "user", "content": "task"}])["extra"]["response_status"] == "filtered"
