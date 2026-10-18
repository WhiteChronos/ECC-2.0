"""Local ECC chat, readiness and real inference acceptance. No target execution."""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
import urllib.request
from datetime import UTC, datetime

from llm.core.types import LLMInput, Message, Role, ToolDefinition
from llm.providers.local_policy import local_base_url, open_local
from llm.providers.ollama import OllamaProvider
from llm.tools import ToolExecutor, ToolRegistry


def _get_json(url: str) -> dict:
    with open_local(urllib.request.Request(url), timeout=5) as response:
        raw = response.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("Resposta acima do limite.")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Resposta invalida.")
    return value


def doctor(provider: OllamaProvider) -> dict:
    version = _get_json(provider.base_url + "/api/version")["version"]
    models = _get_json(provider.base_url + "/api/tags").get("models", [])
    selected = next((item for item in models if item.get("name") == provider.default_model), None)
    if selected:
        provider._verify_local_model(provider.default_model)
    return {
        "ready": selected is not None, "localOnly": True,
        "endpoint": provider.base_url, "runtimeVersion": version,
        "model": provider.default_model, "modelDigest": selected.get("digest") if selected else None,
        "realInferenceVerified": False,
        "code": None if selected else "LOCAL_MODEL_MISSING",
    }


def check_add_code(source: str) -> bool:
    """Validate a fixed harmless coding fixture; never execute generated text."""
    try:
        if len(source) > 4096:
            return False
        tree = ast.parse(source)
        expected = ast.parse("def add(a, b):\n    return a + b")
        return ast.dump(tree) == ast.dump(expected)
    except (SyntaxError, ValueError, RecursionError):
        return False


def smoke(provider: OllamaProvider) -> dict:
    ready = doctor(provider)
    if not ready["ready"]:
        return {**ready, "passed": False}
    checks = []
    schema = {"type": "object", "properties": {"answer": {"type": "integer"}},
              "required": ["answer"], "additionalProperties": False}
    answer = provider.generate(LLMInput(
        messages=[Message(Role.USER, "Calculate 17 + 25. Reply as JSON with the integer in the answer property. /no_think")],
        temperature=0, max_tokens=256, metadata={"think": False, "format": schema},
    ))
    try:
        arithmetic = json.loads(answer.content)
        arithmetic_ok = isinstance(arithmetic, dict) and set(arithmetic) == {"answer"} and type(arithmetic["answer"]) is int and arithmetic["answer"] == 42
    except (ValueError, TypeError):
        arithmetic_ok = False
    checks.append({"name": "real-local-generation", "passed": arithmetic_ok, "observedFixtureAnswer": answer.content[:256]})
    tool = ToolDefinition(
        name="sum_numbers", description="Return the sum of two integers.",
        parameters={"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                    "required": ["a", "b"], "additionalProperties": False},
    )
    output = provider.generate(LLMInput(
        messages=[Message(Role.USER, "Use sum_numbers with a=17 and b=25. Do not calculate yourself. /no_think")],
        tools=[tool], temperature=0, max_tokens=512, metadata={"think": False},
    ))
    registry = ToolRegistry()
    registry.register(tool, lambda a, b: a + b)
    executor = ToolExecutor(registry)
    calls = output.tool_calls or []
    tool_ok = (
        len(calls) == 1 and calls[0].name == "sum_numbers"
        and calls[0].arguments == {"a": 17, "b": 25}
        and executor.execute(calls[0]).content == "42"
    )
    checks.append({"name": "real-local-tool-call", "passed": tool_ok})
    code = provider.generate(LLMInput(
        messages=[Message(Role.USER, "Output only Python source, no markdown. Define add(a, b) returning a + b. No types, comments, imports or docstrings. /no_think")],
        temperature=0, max_tokens=256, metadata={"think": False},
    )).content.strip()
    if code.startswith("```python\n") and code.endswith("```"):
        code = code[len("```python\n"):-3].strip()
    checks.append({"name": "real-local-code-generation-static-check", "passed": check_add_code(code)})
    return {
        **ready, "at": datetime.now(UTC).isoformat(), "passed": all(item["passed"] for item in checks),
        "realInferenceVerified": True, "checks": checks, "paidProviderFallback": False,
        "scope": "Chat local, chamada de ferramenta aritmetica e geracao estatica de fixture. Nao valida todos os hosts ou plugins do ECC.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ECC-2.0 — IA local sem API paga")
    parser.add_argument("--url", default=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11439"))
    parser.add_argument("--model", default=os.environ.get("OLLAMA_MODEL", "qwen3:0.6b"))
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--doctor", action="store_true")
    action.add_argument("--smoke", action="store_true")
    action.add_argument("--prompt")
    action.add_argument("--batch-json")
    args = parser.parse_args(argv)
    os.environ["ECC_LOCAL_ONLY"] = "1"
    os.environ["ECC_SKIP_LLM_SUMMARY"] = "1"
    try:
        batch = None
        if args.batch_json is not None:
            from llm.cli.economy_batch import read_batch
            batch = read_batch(args.batch_json)
        provider = OllamaProvider(base_url=local_base_url(args.url), default_model=args.model)
        if batch is not None:
            from llm.cli.economy_batch import run_batch
            result = run_batch(provider, batch)
            print(json.dumps(result, ensure_ascii=True, indent=2))
            return 0 if result["passed"] else 1
        if args.doctor or args.smoke:
            result = smoke(provider) if args.smoke else doctor(provider)
            print(json.dumps(result, ensure_ascii=True, indent=2))
            return 0 if result.get("passed", result["ready"]) else 1
        if args.prompt is not None:
            output = provider.generate(LLMInput(messages=[Message(Role.USER, args.prompt)], metadata={"think": False}))
            print(output.content)
            return 0
        readiness = doctor(provider)
        if not readiness["ready"]:
            print("Modelo local ausente. Execute --doctor e consulte docs/ECC-LOCAL.md.", file=sys.stderr)
            return 1
        print("ECC-2.0 local. Digite /sair para encerrar. Historico apenas em memoria.")
        messages: list[Message] = []
        while True:
            prompt = input("Voce> ")
            if prompt.strip().lower() == "/sair":
                return 0
            if not prompt.strip():
                continue
            messages = [*messages[-20:], Message(Role.USER, prompt)]
            output = provider.generate(LLMInput(messages=messages, metadata={"think": False}))
            print(f"ECC> {output.content}")
            messages = [*messages, Message(Role.ASSISTANT, output.content)]
    except (EOFError, KeyboardInterrupt):
        return 0
    except Exception as exc:
        print(json.dumps({"ready": False, "passed": False, "code": "LOCAL_RUNTIME_FAILED",
                          "errorType": type(exc).__name__, "failureCode": getattr(exc, "code", None),
                          "causeType": type(exc.__cause__).__name__ if exc.__cause__ else None,
                          "fallbackUsed": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
