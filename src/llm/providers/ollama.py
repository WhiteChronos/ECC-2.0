"""Ollama provider adapter for local models."""

from __future__ import annotations

import json
import logging
import os
import urllib.request
import uuid
from typing import Any

from llm.core.interface import (
    AuthenticationError,
    ContextLengthError,
    LLMError,
    LLMProvider,
    RateLimitError,
)
from llm.core.types import (
    LLMInput,
    LLMOutput,
    Message,
    ModelInfo,
    ProviderType,
    Role,
    ToolCall,
)
from llm.providers.local_policy import local_base_url, local_only_enabled, open_local
from llm.providers.model_config import read_model_env
from llm.providers.reasoning import prefilled_reasoning_from_env, strip_reasoning

logger = logging.getLogger(__name__)


def _messages_payload(messages: list[Message]) -> list[dict[str, Any]]:
    """Serialize messages, naming the tool each tool result answers.

    Ollama correlates a tool result with its call through ``tool_name``; ids
    are optional on its side, so the name is what keeps several results apart.
    """
    names: dict[str, str] = {}
    payload = []
    for msg in messages:
        item = msg.to_dict()
        for tc in msg.tool_calls or []:
            if tc.id:
                names[tc.id] = tc.name
        if msg.role == Role.TOOL:
            tool_name = msg.name or (names.get(msg.tool_call_id) if msg.tool_call_id else None)
            if tool_name:
                item["tool_name"] = tool_name
        payload.append(item)
    return payload


class OllamaProvider(LLMProvider):
    provider_type = ProviderType.OLLAMA

    def __init__(
        self,
        base_url: str | None = None,
        default_model: str | None = None,
        prefilled_reasoning: bool | None = None,
        leading_reasoning: bool | None = None,
    ) -> None:
        # Enable only for a deployment that declares balanced leading reasoning.
        # Generic responses can contain literal XML and stay intact by default.
        self.leading_reasoning = (
            leading_reasoning
            if leading_reasoning is not None
            else prefilled_reasoning_from_env("OLLAMA_LEADING_REASONING")
        )
        # Set for models whose chat template prefills <think>, so replies arrive
        # as "...</think>answer" without the opening tag.
        self.prefilled_reasoning = (
            prefilled_reasoning
            if prefilled_reasoning is not None
            else prefilled_reasoning_from_env("OLLAMA_PREFILLED_REASONING")
        )
        self.base_url = base_url or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        self.local_only = local_only_enabled()
        if self.local_only:
            self.base_url = local_base_url(self.base_url)
        self.default_model = default_model or read_model_env("OLLAMA_MODEL") or "llama3.2"
        self._models = [
            ModelInfo(
                name="llama3.2",
                provider=ProviderType.OLLAMA,
                supports_tools=True,
                supports_vision=False,
                max_tokens=4096,
                context_window=128000,
            ),
            ModelInfo(
                name="mistral",
                provider=ProviderType.OLLAMA,
                supports_tools=True,
                supports_vision=False,
                max_tokens=4096,
                context_window=8192,
            ),
            ModelInfo(
                name="codellama",
                provider=ProviderType.OLLAMA,
                supports_tools=False,
                supports_vision=False,
                max_tokens=4096,
                context_window=16384,
            ),
        ]
        self._tool_support: dict[str, bool] = {}

    def _open(self, request: urllib.request.Request, timeout: float):
        if self.local_only or local_only_enabled():
            return open_local(request, timeout)
        return urllib.request.urlopen(request, timeout=timeout)

    def _verify_local_model(self, model: str) -> None:
        if ":cloud" in model.lower() or model.lower().endswith("-cloud"):
            raise ValueError("Modo local: modelo cloud bloqueado.")
        req = urllib.request.Request(
            f"{self.base_url}/api/show", data=json.dumps({"model": model}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with self._open(req, timeout=10) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError("Modo local: metadados acima do limite.")
        info = json.loads(raw)
        if info.get("remote_host") or info.get("remote_model") or not info.get("model_info"):
            raise ValueError("Modo local: pesos locais nao comprovados.")

    def model_supports_tools(self, model: str) -> bool:
        """Whether ``model`` declares tool support.

        Catalogued models answer from :attr:`ModelInfo.supports_tools`. Any other
        model is looked up once through ``/api/show``, whose ``capabilities``
        list is what the installed model itself declares. Only an answered lookup
        is cached: a failed one counts as no tool support for that request and
        is retried on the next.
        """
        for info in self._models:
            if info.name == model:
                return info.supports_tools
        if model in self._tool_support:
            return self._tool_support[model]
        try:
            req = urllib.request.Request(
                f"{self.base_url}/api/show",
                data=json.dumps({"model": model}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with self._open(req, timeout=10) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
                if len(raw) > 8 * 1024 * 1024:
                    raise ValueError("Capacidades acima do limite.")
                capabilities = json.loads(raw.decode("utf-8")).get("capabilities") or []
        except Exception as e:
            logger.warning("Could not read capabilities for Ollama model '%s': %s", model, type(e).__name__)
            return False
        if not isinstance(capabilities, list) or not all(isinstance(item, str) for item in capabilities):
            logger.warning("Invalid capabilities for Ollama model '%s'; sending no tools", model)
            return False
        supports_tools = "tools" in capabilities
        self._tool_support = {**self._tool_support, model: supports_tools}
        return supports_tools

    def generate(self, input: LLMInput) -> LLMOutput:
        try:
            url = f"{self.base_url}/api/chat"
            model = input.model or self.default_model
            if self.local_only or local_only_enabled():
                self._verify_local_model(model)

            payload: dict[str, Any] = {
                "model": model,
                "messages": _messages_payload(input.messages),
                "stream": False,
            }
            if "think" in input.metadata:
                if not isinstance(input.metadata["think"], bool):
                    raise ValueError("think deve ser booleano.")
                payload["think"] = input.metadata["think"]
            if "format" in input.metadata:
                schema = input.metadata["format"]
                if not isinstance(schema, dict) or len(json.dumps(schema)) > 16384:
                    raise ValueError("Schema JSON invalido ou acima do limite.")
                payload["format"] = schema
            options: dict[str, Any] = {}
            if input.temperature != 1.0:
                options["temperature"] = input.temperature
            if input.max_tokens is not None:
                options["num_predict"] = input.max_tokens
            if options:
                payload["options"] = options
            if input.tools:
                if self.model_supports_tools(model):
                    payload["tools"] = [tool.to_openai_tool() for tool in input.tools]
                else:
                    logger.warning("Ollama model '%s' does not declare tool support; sending no tools", model)

            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})

            timeout = 180 if self.local_only or local_only_enabled() else 60
            with self._open(req, timeout=timeout) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
                if len(raw) > 8 * 1024 * 1024:
                    raise ValueError("Resposta acima do limite.")
                result = json.loads(raw.decode("utf-8"))

            content = strip_reasoning(
                result.get("message", {}).get("content", ""),
                leading=self.leading_reasoning,
                prefilled=self.prefilled_reasoning
            )

            tool_calls = None
            if result.get("message", {}).get("tool_calls"):
                tool_calls = [
                    ToolCall(
                        # Native Ollama calls often carry no id; give each one a
                        # unique id so its result can be matched to it.
                        id=tc.get("id") or f"call_{uuid.uuid4().hex[:24]}",
                        name=tc.get("function", {}).get("name", ""),
                        arguments=tc.get("function", {}).get("arguments", {}),
                    )
                    for tc in result["message"]["tool_calls"]
                ]

            return LLMOutput(
                content=content,
                tool_calls=tool_calls,
                model=model,
                stop_reason=result.get("done_reason"),
            )
        except Exception as e:
            if self.local_only or local_only_enabled():
                raise LLMError(
                    f"Modo local: requisicao falhou ({type(e).__name__}); sem fallback externo.",
                    provider=ProviderType.OLLAMA, code="local_request_failed",
                ) from e
            msg = str(e)
            lowered = msg.lower()
            if "401" in msg or "unauthorized" in lowered or "forbidden" in lowered:
                raise AuthenticationError(f"Ollama authentication failed: {msg}", provider=ProviderType.OLLAMA) from e
            if "429" in msg or "rate_limit" in lowered:
                raise RateLimitError(msg, provider=ProviderType.OLLAMA) from e
            if "context" in lowered and "length" in lowered:
                raise ContextLengthError(msg, provider=ProviderType.OLLAMA) from e
            if (
                "connection" in lowered
                or "refused" in lowered
                or "timed out" in lowered
                or "timeout" in lowered
                or "unreachable" in lowered
                or "name resolution" in lowered
                or "nodename nor servname" in lowered
                or isinstance(e, (ConnectionError, TimeoutError))
            ):
                raise LLMError(
                    f"Ollama connection failed: {type(e).__name__}",
                    provider=ProviderType.OLLAMA,
                    code="connection_error",
                ) from e
            raise LLMError(
                f"Ollama request failed: {type(e).__name__}",
                provider=ProviderType.OLLAMA,
                code="provider_error",
            ) from e

    def list_models(self) -> list[ModelInfo]:
        return self._models.copy()

    def validate_config(self) -> bool:
        return bool(self.base_url)

    def get_default_model(self) -> str:
        return self.default_model
