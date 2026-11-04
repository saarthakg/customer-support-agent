"""The openai boundary: transport failures become LLMError, which the loop turns into a fallback (D-26)."""

from types import SimpleNamespace

import openai
import pytest

from agent import config
from agent.llm import LLM, LLMError


def response(status: int) -> SimpleNamespace:
    # Just enough of an HTTP response for openai's error classes, without importing its transport library.
    return SimpleNamespace(request=None, status_code=status, headers={})


@pytest.fixture
def llm(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    return LLM()


def test_client_uses_configured_timeout_and_retries(llm):
    assert llm._client.timeout == config.REQUEST_TIMEOUT_S
    assert llm._client.max_retries == config.MAX_RETRIES


@pytest.mark.parametrize(
    "error",
    [
        openai.APITimeoutError(request=None),
        openai.RateLimitError("rate limited", response=response(429), body=None),
        openai.APIConnectionError(request=None),
        openai.InternalServerError("upstream", response=response(500), body=None),
    ],
)
def test_transport_failures_become_llm_error(llm, monkeypatch, error):
    # Raised after the client's own retries are spent; nothing openai-typed escapes llm.py.
    def fail(**kwargs):
        raise error

    monkeypatch.setattr(llm._client.chat.completions, "create", fail)
    with pytest.raises(LLMError):
        llm.complete([{"role": "user", "content": "hi"}], tools=[])
