"""Local-only profile must fail closed before any remote model call."""

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from llm.core.types import LLMInput, Message, Role
from llm.providers import (
    AstraflowCNProvider,
    AstraflowProvider,
    AtlasProvider,
    ClaudeProvider,
    OllamaProvider,
    OpenAIProvider,
    get_provider,
)


@pytest.fixture(autouse=True)
def local_profile(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ECC_LOCAL_ONLY", "1")
    for key in ("LLM_PROVIDER", "LLM_MODEL", "OLLAMA_BASE_URL", "OLLAMA_MODEL"):
        monkeypatch.delenv(key, raising=False)


def test_local_profile_defaults_to_ollama_without_reading_paid_config(tmp_path):
    tmp_path.joinpath(".llm.env").write_text("LLM_PROVIDER=claude\nLLM_MODEL=paid\n")
    assert isinstance(get_provider(), OllamaProvider)


@pytest.mark.parametrize("provider", ["claude", "openai", "atlas", "astraflow", "astraflow_cn"])
def test_local_profile_refuses_external_provider(provider):
    with pytest.raises(ValueError, match="local"):
        get_provider(provider)


@pytest.mark.parametrize("factory", [ClaudeProvider, OpenAIProvider, AtlasProvider, AstraflowProvider, AstraflowCNProvider])
def test_direct_external_constructor_is_blocked(factory):
    with pytest.raises(ValueError, match="local"):
        factory()


@pytest.mark.parametrize("url", [
    "https://ollama.com", "http://example.com", "http://127.0.0.1.evil.test",
    "http://user:secret@127.0.0.1", "http://127.0.0.1/api", "http://127.0.0.1?x=1",
])
def test_local_profile_refuses_remote_or_ambiguous_endpoint(url):
    with pytest.raises(ValueError, match="local"):
        OllamaProvider(base_url=url)


def test_local_profile_normalizes_localhost():
    assert OllamaProvider(base_url="http://localhost:11434").base_url == "http://127.0.0.1:11434"


@pytest.fixture
def local_server():
    calls = []
    state = {"remote": False, "redirect": False}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            result = {"models": [{"name": "fixture", "digest": "sha256:fixture"}]} if self.path == "/api/tags" else {"version": "fixture"}
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

        def do_POST(self):
            calls.append(self.path)
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["last_payload"] = body
            if state["redirect"]:
                self.send_response(307)
                self.send_header("Location", "http://example.com/never-follow")
                self.end_headers()
                return
            if self.path == "/api/show":
                result = {"model_info": {"general.architecture": "qwen3"}, "capabilities": ["completion", "tools"]}
                if state["remote"]:
                    result["remote_host"] = "https://ollama.com"
            else:
                result = {"message": {"content": "local ok"}, "model": body["model"]}
                prompt = body.get("messages", [{}])[-1].get("content", "") if body.get("messages") else ""
                if "17 + 25" in prompt:
                    result["message"]["content"] = json.dumps({"answer": 43 if state.get("wrong_answer") else 42}) if body.get("format") else "42"
                if body.get("tools"):
                    result["message"] = {"content": "", "tool_calls": [{"function": {"name": "sum_numbers", "arguments": {"a": 17, "b": 25}}}]}
                if "Define add(a, b)" in prompt:
                    result["message"]["content"] = "def add(a, b):\n    return a + b"
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", calls, state
    server.shutdown()
    server.server_close()
    thread.join()


def test_local_request_ignores_proxy_and_checks_model(local_server, monkeypatch):
    url, calls, _ = local_server
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    provider = OllamaProvider(base_url=url, default_model="fixture")
    assert provider.generate(LLMInput(messages=[Message(Role.USER, "hello")])).content == "local ok"
    assert calls == ["/api/show", "/api/chat"]


def test_local_request_rejects_cloud_model_before_chat(local_server):
    url, calls, state = local_server
    state["remote"] = True
    with pytest.raises(Exception, match="local|Local"):
        OllamaProvider(base_url=url, default_model="fixture").generate(LLMInput(messages=[]))
    assert calls == ["/api/show"]


def test_local_request_never_follows_redirect(local_server):
    url, calls, state = local_server
    state["redirect"] = True
    with pytest.raises(Exception):
        OllamaProvider(base_url=url, default_model="fixture").generate(LLMInput(messages=[]))
    assert calls == ["/api/show"]


def test_local_cli_doctor_and_prompt(local_server, capsys):
    assert importlib.util.find_spec("llm.cli.local") is not None, "Local CLI is not implemented"
    from llm.cli.local import main
    url, _, _ = local_server
    assert main(["--url", url, "--model", "fixture", "--doctor"]) == 0
    assert json.loads(capsys.readouterr().out)["ready"] is True
    assert main(["--url", url, "--model", "fixture", "--prompt", "hello"]) == 0
    assert capsys.readouterr().out.strip() == "local ok"


def test_local_cli_missing_model_fails(local_server, capsys):
    assert importlib.util.find_spec("llm.cli.local") is not None, "Local CLI is not implemented"
    from llm.cli.local import main
    url, _, _ = local_server
    assert main(["--url", url, "--model", "missing", "--doctor"]) == 1
    assert json.loads(capsys.readouterr().out)["ready"] is False


def test_local_cli_smoke_uses_local_provider_and_registered_tool(local_server, capsys):
    from llm.cli.local import main
    url, calls, _ = local_server
    assert main(["--url", url, "--model", "fixture", "--smoke"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["passed"] is True
    assert len(result["checks"]) == 3
    assert result["paidProviderFallback"] is False
    assert calls.count("/api/chat") == 3


def test_smoke_code_validator_rejects_arbitrary_execution():
    assert importlib.util.find_spec("llm.cli.local") is not None, "Local CLI is not implemented"
    from llm.cli.local import check_add_code
    assert check_add_code("def add(a, b):\n    return a + b") is True
    for source in ("import os", "def add(a,b):\n return __import__('os')", "def add(a,b):\n return a-b"):
        assert check_add_code(source) is False
    assert check_add_code("x" * 4097) is False
    assert check_add_code("def invalid(") is False


def test_local_cli_interactive_session(local_server, monkeypatch, capsys):
    from llm.cli.local import main
    url, _, _ = local_server
    lines = iter(["", "hello", "/sair"])
    monkeypatch.setattr("builtins.input", lambda _: next(lines))
    assert main(["--url", url, "--model", "fixture"]) == 0
    assert "ECC> local ok" in capsys.readouterr().out


def test_local_cli_missing_model_in_chat(local_server, capsys):
    from llm.cli.local import main
    url, _, _ = local_server
    assert main(["--url", url, "--model", "missing"]) == 1
    assert "Modelo local ausente" in capsys.readouterr().err


def test_local_cli_rejects_remote_url_without_network(capsys):
    from llm.cli.local import main
    assert main(["--url", "https://example.com", "--doctor"]) == 1
    assert json.loads(capsys.readouterr().out)["fallbackUsed"] is False


def test_local_cli_eof_is_clean(local_server, monkeypatch):
    from llm.cli.local import main
    url, _, _ = local_server
    def end(_):
        raise EOFError
    monkeypatch.setattr("builtins.input", end)
    assert main(["--url", url, "--model", "fixture"]) == 0


def test_invalid_local_flag_is_rejected(monkeypatch):
    monkeypatch.setenv("ECC_LOCAL_ONLY", "typo")
    with pytest.raises(ValueError, match="local"):
        get_provider()


def test_local_cold_start_has_bounded_180_second_timeout(local_server, monkeypatch):
    url, _, state = local_server
    provider = OllamaProvider(base_url=url, default_model="fixture")
    original = provider._open
    timeouts = []
    def observe(request, timeout):
        timeouts.append(timeout)
        return original(request, timeout)
    monkeypatch.setattr(provider, "_open", observe)
    provider.generate(LLMInput(messages=[], metadata={"think": False}))
    assert timeouts == [10, 180]
    assert state["last_payload"]["think"] is False


def test_local_structured_output_is_forwarded(local_server):
    url, _, state = local_server
    schema = {"type": "object", "properties": {"answer": {"type": "integer"}}, "required": ["answer"]}
    OllamaProvider(base_url=url, default_model="fixture").generate(LLMInput(messages=[], metadata={"format": schema}))
    assert state["last_payload"]["format"] == schema


def test_smoke_wrong_arithmetic_is_not_accepted(local_server, capsys):
    from llm.cli.local import main
    url, _, state = local_server
    state["wrong_answer"] = True
    assert main(["--url", url, "--model", "fixture", "--smoke"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["passed"] is False
    assert result["checks"][0]["passed"] is False
