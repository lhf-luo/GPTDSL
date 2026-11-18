"""Mocked Chat Completions contract and source-evidence validation."""

from dataclasses import replace
from http.client import IncompleteRead
from io import BytesIO
import json
from types import SimpleNamespace
from urllib import error

import pytest

from gptdsl.patch_context import prepare_patch_context
from gptdsl.patch_selection import Evidence, ReviewError, SemanticReview
from gptdsl.patch_selection.provider import ChatCompletionsReviewer, ReviewConfig, _NoRedirect
from gptdsl.patch_selection.review import parse_review, validate_review


@pytest.fixture
def context(history):
    history.write("sample.c", "int value(void) { return 1; }\n")
    history.commit("base")
    history.write("sample.c", "int value(void) { return 2; }\n")
    return prepare_patch_context(history.path, history.commit("adjust"))


def install_endpoint(monkeypatch, payload):
    calls = []

    def open_request(message, timeout):
        calls.append((message, timeout))
        if isinstance(payload, Exception):
            raise payload
        return BytesIO(payload)

    def build_opener(*handlers):
        assert any(isinstance(handler, _NoRedirect) for handler in handlers)
        return SimpleNamespace(open=open_request)

    monkeypatch.setattr("gptdsl.patch_selection.provider.request.build_opener", build_opener)
    return calls


@pytest.mark.parametrize("fenced", [False, True])
def test_request_and_audit_are_reproducible_without_credentials(context, monkeypatch, fenced):
    answer = json.dumps(dict(decision="needs_review", category="unknown", reason="Insufficient evidence"))
    content = f"```json\n{answer}\n```" if fenced else answer
    response = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
    calls = install_endpoint(monkeypatch, response)
    config = ReviewConfig(api_key="private-test-key", timeout=5)
    review = ChatCompletionsReviewer(config).review(context)
    message, timeout = calls[0]
    assert message.full_url == "https://api.deepseek.com/v1/chat/completions"
    assert message.method == "POST" and timeout == 5
    assert message.get_header("Authorization") == "Bearer private-test-key"
    body = json.loads(message.data)
    assert body["model"] == "deepseek-flash"
    assert body["messages"][1]["content"] == context.markdown
    assert body["response_format"] == {"type": "json_object"}
    assert "private-test-key" not in repr(config) + json.dumps(review.audit)
    assert review.audit["raw_content"] == content
    assert len(review.audit["request_sha256"]) == len(review.audit["response_sha256"]) == 64
    assert ChatCompletionsReviewer(config).review(context) == review


@pytest.mark.parametrize("payload,message", [
    (b"not json", "Invalid JSON"),
    (b'{"choices":[]}', "Invalid JSON"),
    (b'{"choices":[{"message":{"content":null}}]}', "Invalid JSON"),
    (b"x" * (1024 * 1024 + 1), "exceeds 1 MiB"),
    (error.HTTPError("http://test", 429, "secret body", {}, None), "HTTP 429"),
    (error.HTTPError("http://test", 302, "redirect", {}, None), "HTTP 302"),
    (error.URLError("private connection details"), "unavailable or timed out"),
    (TimeoutError("private connection details"), "unavailable or timed out"),
    (IncompleteRead(b"partial", 10), "unavailable or timed out"),
])
def test_provider_failures_are_bounded_and_sanitized(context, monkeypatch, payload, message):
    install_endpoint(monkeypatch, payload)
    with pytest.raises(ReviewError, match=message) as caught:
        ChatCompletionsReviewer(ReviewConfig("test")).review(context)
    assert "private" not in str(caught.value) and "secret" not in str(caught.value)


def test_config_environment_and_invalid_settings(monkeypatch):
    monkeypatch.setenv("GPTDSL_REVIEW_MODEL", "configured-model")
    monkeypatch.setenv("GPTDSL_REVIEW_BASE_URL", "http://localhost/v1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    assert ReviewConfig.from_env(None, None) == ReviewConfig("configured-model", "http://localhost/v1", "test-key")
    assert ReviewConfig.from_env("override", "http://other/v1").model == "override"
    for kwargs in ({"model": ""}, {"base_url": "file:///local"}, {"timeout": 0},
                   {"base_url": "https://user:pass@example.test/v1"},
                   {"base_url": "https://example.test/v1?api_key=secret"}):
        with pytest.raises(ValueError):
            ReviewConfig(**({"model": "test"} | kwargs))


def test_deepseek_defaults_and_key_source(monkeypatch):
    monkeypatch.delenv("GPTDSL_REVIEW_MODEL", raising=False)
    monkeypatch.delenv("GPTDSL_REVIEW_BASE_URL", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    monkeypatch.setenv("GPTDSL_REVIEW_API_KEY", "legacy-key")
    monkeypatch.setenv("OPENAI_API_KEY", "other-provider-key")
    config = ReviewConfig.from_env()
    assert config.model == "deepseek-flash"
    assert config.base_url == "https://api.deepseek.com/v1"
    assert config.api_key == "deepseek-test-key"
    assert "deepseek-test-key" not in repr(config)


@pytest.mark.parametrize("key", [None, "", "   "])
def test_missing_deepseek_key_fails_without_legacy_fallback(monkeypatch, key):
    monkeypatch.setenv("OPENAI_API_KEY", "other-provider-key")
    monkeypatch.setenv("GPTDSL_REVIEW_API_KEY", "legacy-key")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    if key is not None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", key)
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        ReviewConfig.from_env()


def test_redirects_are_rejected():
    assert _NoRedirect().redirect_request(None, None, 302, "redirect", {}, "http://other") is None


@pytest.mark.parametrize("payload", [
    [], {}, {"decision": "accept", "category": "other", "reason": "unknown decision"},
    {"decision": "suitable", "category": "other", "reason": "", "evidence": []},
    {"decision": "suitable", "category": "other", "reason": "reason", "evidence": {}},
    {"decision": "suitable", "category": "other", "reason": "reason", "evidence": [
        dict(revision="sha", path="a.c", start_line=True, end_line=2, quote="code")]},
])
def test_malformed_semantic_review(payload):
    with pytest.raises(ReviewError):
        parse_review(payload)


def test_evidence_must_be_at_claimed_lines_and_visible_to_reviewer(context):
    source = context.functions[0].after
    evidence = Evidence(source.revision, source.path, source.start_line, source.end_line, source.text)
    review = SemanticReview("suitable", "error_handling", "A local change", (evidence,))
    validate_review(review, context)
    with pytest.raises(ReviewError, match="visible historical source"):
        validate_review(review, replace(context, markdown="Source was not shown"))
    wrong = replace(evidence, quote=context.functions[0].before.text)
    with pytest.raises(ReviewError, match="visible historical source"):
        validate_review(replace(review, evidence=(wrong,)), context)
