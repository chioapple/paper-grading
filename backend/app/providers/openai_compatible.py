"""显式能力驱动的 OpenAI-compatible Chat Completions 适配器。"""

import asyncio
import hashlib

from app.domain.enums import ProviderType
from app.providers.base import (
    ProviderAdapterBase,
    ProviderAdapterError,
    ProviderAdapterHttpClient,
    ProviderGradeRequest,
    ProviderGradeResult,
    ProviderHttpResponse,
    ProviderTokenUsage,
    raise_for_provider_status,
)
from app.providers.connection import ProviderBaseUrlPolicy
from app.providers.schema import compile_provider_schema


class OpenAICompatibleAdapter(ProviderAdapterBase):
    """只按已确认能力发参数，不从模型名称猜测或自动降级。"""

    provider_type = ProviderType.OPENAI_COMPATIBLE

    def __init__(
        self,
        *,
        url_policy: ProviderBaseUrlPolicy,
        http_client: ProviderAdapterHttpClient,
    ) -> None:
        self._url_policy = url_policy
        self._http_client = http_client

    def _validate_capabilities(self, request: ProviderGradeRequest) -> None:
        capabilities = request.capabilities
        schema_pair = (capabilities.structured_output, capabilities.schema_dialect)
        if request.provider_type is not self.provider_type or schema_pair not in {
            ("json_object", "canonical"),
            ("json_schema", "openai"),
        }:
            raise ProviderAdapterError(
                "provider_capability_unsupported",
                "兼容模型能力快照不受当前适配器支持",
            )

    def _raise_for_status(self, response: ProviderHttpResponse) -> None:
        raise_for_provider_status(response, provider_type=self.provider_type)

    @staticmethod
    def _response_format(request: ProviderGradeRequest) -> tuple[dict[str, object], bytes]:
        capabilities = request.capabilities
        if capabilities.structured_output == "json_object":
            return {"type": "json_object"}, request.prompt.result_schema_hash
        compiled = compile_provider_schema(request.result_schema_json, dialect="openai")
        return (
            {
                "type": "json_schema",
                "json_schema": {
                    "name": "grade_result",
                    "strict": True,
                    "schema": compiled.schema_body,
                },
            },
            compiled.sha256,
        )

    @staticmethod
    def _sampling_parameters(request: ProviderGradeRequest) -> dict[str, object]:
        policy = request.capabilities.sampling_policy
        if policy == "temperature_zero":
            return {"temperature": 0}
        if policy == "temperature_fixed_0_6":
            return {"temperature": 0.6}
        if policy == "do_sample_false":
            return {"do_sample": False}
        return {}

    @staticmethod
    def _thinking_parameters(request: ProviderGradeRequest) -> dict[str, object]:
        policy = request.capabilities.thinking_policy
        if policy == "disabled":
            return {"thinking": {"type": "disabled"}}
        if policy == "enabled":
            return {"thinking": {"type": "enabled"}}
        return {}

    async def grade(self, request: ProviderGradeRequest) -> ProviderGradeResult:
        self._validate_capabilities(request)
        capabilities = request.capabilities
        response_format, sent_schema_sha256 = self._response_format(request)
        body: dict[str, object] = {
            "model": request.model,
            "messages": [message.model_dump() for message in request.prompt.messages],
            "response_format": response_format,
            capabilities.output_token_parameter: request.max_output_tokens,
            "stream": False,
            **self._sampling_parameters(request),
            **self._thinking_parameters(request),
        }
        try:
            async with asyncio.timeout(float(request.timeout_seconds)):
                target = await self._url_policy.validate(self.provider_type, request.base_url)
                response = await self._http_client.post_json(
                    target=target,
                    url=f"{target.value}/chat/completions",
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {request.api_key.get_secret_value()}",
                    },
                    json_body=body,
                    timeout_seconds=request.timeout_seconds,
                )
        except TimeoutError as error:
            raise ProviderAdapterError(
                "provider_timeout",
                "供应商评分请求超时",
                retryable=True,
            ) from error
        self._raise_for_status(response)
        payload = response.json_body
        try:
            if not isinstance(payload, dict) or payload.get("object") != "chat.completion":
                raise TypeError
            request_id = payload["id"]
            reported_model = payload["model"]
            if not isinstance(request_id, str) or not request_id:
                raise TypeError
            if not isinstance(reported_model, str) or not reported_model:
                raise TypeError
            choices = payload["choices"]
            if not isinstance(choices, list) or len(choices) != 1:
                raise TypeError
            choice = choices[0]
            if not isinstance(choice, dict) or choice.get("index") != 0:
                raise TypeError
            finish_reason = choice.get("finish_reason")
            if finish_reason == "length":
                raise ProviderAdapterError(
                    "provider_output_truncated",
                    "供应商响应因长度限制被截断",
                    response=response,
                )
            if finish_reason in {"content_filter", "sensitive"}:
                raise ProviderAdapterError(
                    "provider_content_refused",
                    "供应商拒绝了该评分内容",
                    response=response,
                )
            if finish_reason == "model_context_window_exceeded":
                raise ProviderAdapterError(
                    "provider_context_exceeded",
                    "评分请求超过模型上下文上限",
                    response=response,
                )
            if finish_reason != "stop":
                raise TypeError
            message = choice["message"]
            if not isinstance(message, dict) or message.get("role") != "assistant":
                raise TypeError
            output_text = message["content"]
            if not isinstance(output_text, str) or not output_text.strip():
                raise TypeError
            usage = payload["usage"]
            if not isinstance(usage, dict):
                raise TypeError
            input_tokens = usage["prompt_tokens"]
            output_tokens = usage["completion_tokens"]
            total_tokens = usage["total_tokens"]
            input_details = usage.get("prompt_tokens_details", {})
            output_details = usage.get("completion_tokens_details", {})
            if not isinstance(input_details, dict) or not isinstance(output_details, dict):
                raise TypeError
            cached_tokens = input_details.get("cached_tokens", 0)
            reasoning_tokens = output_details.get("reasoning_tokens", 0)
            if (
                any(
                    type(value) is not int or value < 0
                    for value in (
                        input_tokens,
                        output_tokens,
                        total_tokens,
                        cached_tokens,
                        reasoning_tokens,
                    )
                )
                or total_tokens != input_tokens + output_tokens
            ):
                raise TypeError
        except (KeyError, TypeError) as error:
            raise ProviderAdapterError(
                "provider_response_invalid",
                "兼容供应商返回了无效评分响应",
                response=response,
            ) from error

        normalized_usage = ProviderTokenUsage(
            input_tokens=input_tokens,
            cached_input_tokens=cached_tokens,
            cache_write_input_tokens=0,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            total_tokens=total_tokens,
        )
        return ProviderGradeResult(
            provider_type=self.provider_type,
            requested_model=request.model,
            reported_model=reported_model,
            request_id=request_id,
            output_text=output_text,
            usage=normalized_usage,
            estimated_cost=self.estimate_cost(
                usage=normalized_usage,
                pricing=capabilities.pricing,
            ),
            raw_response=response.raw_body,
            raw_response_sha256=hashlib.sha256(response.raw_body).digest(),
            sent_schema_sha256=sent_schema_sha256,
        )
