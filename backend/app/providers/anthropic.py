"""Anthropic Messages API 评分适配器。"""

import asyncio
import hashlib

from app.domain.enums import ProviderType
from app.providers.base import (
    ProviderAdapterBase,
    ProviderAdapterError,
    ProviderAdapterHttpClient,
    ProviderGradeRequest,
    ProviderGradeResult,
    ProviderTokenUsage,
    raise_for_provider_status,
)
from app.providers.connection import ProviderBaseUrlPolicy
from app.providers.schema import compile_provider_schema


class AnthropicAdapter(ProviderAdapterBase):
    """使用 Messages API 原生结构化输出执行评分。"""

    provider_type = ProviderType.ANTHROPIC

    def __init__(
        self,
        *,
        url_policy: ProviderBaseUrlPolicy,
        http_client: ProviderAdapterHttpClient,
    ) -> None:
        self._url_policy = url_policy
        self._http_client = http_client

    async def grade(self, request: ProviderGradeRequest) -> ProviderGradeResult:
        capabilities = request.capabilities
        if request.provider_type is not ProviderType.ANTHROPIC or (
            capabilities.structured_output != "json_schema"
            or capabilities.schema_dialect != "anthropic"
            or capabilities.sampling_policy != "omit"
            or capabilities.thinking_policy != "omit"
            or capabilities.output_token_parameter != "max_tokens"
        ):
            raise ProviderAdapterError(
                "provider_capability_unsupported",
                "Anthropic 模型能力快照不受当前适配器支持",
            )
        if request.prompt.messages[0].role != "system" or any(
            message.role != "user" for message in request.prompt.messages[1:]
        ):
            raise ProviderAdapterError(
                "provider_request_invalid",
                "Anthropic 评分提示消息结构无效",
            )
        compiled_schema = compile_provider_schema(
            request.result_schema_json,
            dialect="anthropic",
        )
        try:
            async with asyncio.timeout(float(request.timeout_seconds)):
                target = await self._url_policy.validate(ProviderType.ANTHROPIC, request.base_url)
                response = await self._http_client.post_json(
                    target=target,
                    url=f"{target.value}/v1/messages",
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "anthropic-version": "2023-06-01",
                        "x-api-key": request.api_key.get_secret_value(),
                    },
                    json_body={
                        "model": request.model,
                        "system": request.prompt.messages[0].content,
                        "messages": [
                            {"role": message.role, "content": message.content}
                            for message in request.prompt.messages[1:]
                        ],
                        "output_config": {
                            "format": {
                                "type": "json_schema",
                                "schema": compiled_schema.schema_body,
                            }
                        },
                        "max_tokens": request.max_output_tokens,
                        "stream": False,
                    },
                    timeout_seconds=request.timeout_seconds,
                )
        except TimeoutError as error:
            raise ProviderAdapterError(
                "provider_timeout",
                "Anthropic 评分请求超时",
                retryable=True,
            ) from error
        raise_for_provider_status(response, provider_type=ProviderType.ANTHROPIC)
        payload = response.json_body
        try:
            if (
                not isinstance(payload, dict)
                or payload.get("type") != "message"
                or payload.get("role") != "assistant"
            ):
                raise TypeError
            stop_reason = payload.get("stop_reason")
            if stop_reason == "max_tokens":
                raise ProviderAdapterError(
                    "provider_output_truncated",
                    "Anthropic 输出达到上限",
                    response=response,
                )
            if stop_reason == "model_context_window_exceeded":
                raise ProviderAdapterError(
                    "provider_context_exceeded",
                    "评分请求超过 Anthropic 模型上下文上限",
                    response=response,
                )
            if stop_reason == "refusal":
                raise ProviderAdapterError(
                    "provider_content_refused",
                    "Anthropic 拒绝了该评分内容",
                    response=response,
                )
            if stop_reason != "end_turn":
                raise TypeError
            request_id = payload["id"]
            reported_model = payload["model"]
            if not isinstance(request_id, str) or not request_id:
                raise TypeError
            if not isinstance(reported_model, str) or not reported_model:
                raise TypeError
            content = payload["content"]
            if not isinstance(content, list) or len(content) != 1:
                raise TypeError
            content_block = content[0]
            if not isinstance(content_block, dict) or content_block.get("type") != "text":
                raise TypeError
            output_text = content_block["text"]
            if not isinstance(output_text, str) or not output_text.strip():
                raise TypeError
            usage = payload["usage"]
            if not isinstance(usage, dict):
                raise TypeError
            input_tokens = usage["input_tokens"]
            cache_write_tokens = usage.get("cache_creation_input_tokens", 0)
            cache_read_tokens = usage.get("cache_read_input_tokens", 0)
            output_tokens = usage["output_tokens"]
            if any(
                type(value) is not int or value < 0
                for value in (
                    input_tokens,
                    cache_write_tokens,
                    cache_read_tokens,
                    output_tokens,
                )
            ):
                raise TypeError
        except (KeyError, TypeError) as error:
            raise ProviderAdapterError(
                "provider_response_invalid",
                "Anthropic 返回了无效评分响应",
                response=response,
            ) from error

        total_input_tokens = input_tokens + cache_write_tokens + cache_read_tokens
        normalized_usage = ProviderTokenUsage(
            input_tokens=total_input_tokens,
            cached_input_tokens=cache_read_tokens,
            cache_write_input_tokens=cache_write_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=0,
            total_tokens=None,
        )
        return ProviderGradeResult(
            provider_type=ProviderType.ANTHROPIC,
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
            sent_schema_sha256=compiled_schema.sha256,
        )
