"""DeepSeek 评分适配器。"""

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


class DeepSeekAdapter(ProviderAdapterBase):
    """使用 DeepSeek Chat Completions 执行一次严格 JSON 评分。"""

    provider_type = ProviderType.DEEPSEEK

    def __init__(
        self,
        *,
        url_policy: ProviderBaseUrlPolicy,
        http_client: ProviderAdapterHttpClient,
    ) -> None:
        self._url_policy = url_policy
        self._http_client = http_client

    async def grade(self, request: ProviderGradeRequest) -> ProviderGradeResult:
        if request.provider_type is not ProviderType.DEEPSEEK:
            raise ProviderAdapterError(
                "provider_capability_unsupported",
                "适配器与供应商类型不一致",
            )
        capabilities = request.capabilities
        if (
            capabilities.structured_output != "json_object"
            or capabilities.schema_dialect != "canonical"
            or capabilities.sampling_policy != "temperature_zero"
            or capabilities.thinking_policy != "disabled"
            or capabilities.output_token_parameter != "max_tokens"
        ):
            raise ProviderAdapterError(
                "provider_capability_unsupported",
                "DeepSeek 模型能力快照不受当前适配器支持",
            )
        try:
            async with asyncio.timeout(float(request.timeout_seconds)):
                target = await self._url_policy.validate(
                    ProviderType.DEEPSEEK,
                    request.base_url,
                )
                response = await self._http_client.post_json(
                    target=target,
                    url=f"{target.value}/chat/completions",
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {request.api_key.get_secret_value()}",
                    },
                    json_body={
                        "model": request.model,
                        "messages": [message.model_dump() for message in request.prompt.messages],
                        "response_format": {"type": "json_object"},
                        "temperature": 0,
                        "max_tokens": request.max_output_tokens,
                        "stream": False,
                        "thinking": {"type": "disabled"},
                    },
                    timeout_seconds=request.timeout_seconds,
                )
        except TimeoutError as error:
            raise ProviderAdapterError(
                "provider_timeout",
                "DeepSeek 评分请求超时",
                retryable=True,
            ) from error
        raise_for_provider_status(response, provider_type=ProviderType.DEEPSEEK)
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
                    "DeepSeek 响应因长度限制被截断",
                    response=response,
                )
            if finish_reason == "content_filter":
                raise ProviderAdapterError(
                    "provider_content_refused",
                    "DeepSeek 拒绝了该评分内容",
                    response=response,
                )
            if finish_reason != "stop":
                raise TypeError
            message = choice["message"]
            if (
                not isinstance(message, dict)
                or message.get("role") != "assistant"
                or message.get("reasoning_content") not in {None, ""}
            ):
                raise TypeError
            content = message["content"]
            if not isinstance(content, str) or not content.strip():
                raise TypeError
            usage = payload["usage"]
            if not isinstance(usage, dict):
                raise TypeError
            prompt_tokens = usage["prompt_tokens"]
            completion_tokens = usage["completion_tokens"]
            total_tokens = usage["total_tokens"]
            cache_hit_tokens = usage.get("prompt_cache_hit_tokens", 0)
            cache_miss_tokens = usage.get("prompt_cache_miss_tokens", prompt_tokens)
            if (
                any(
                    type(value) is not int or value < 0
                    for value in (
                        prompt_tokens,
                        completion_tokens,
                        total_tokens,
                        cache_hit_tokens,
                        cache_miss_tokens,
                    )
                )
                or total_tokens != prompt_tokens + completion_tokens
                or cache_hit_tokens + cache_miss_tokens != prompt_tokens
            ):
                raise TypeError
        except (KeyError, TypeError) as error:
            raise ProviderAdapterError(
                "provider_response_invalid",
                "DeepSeek 返回了无效评分响应",
            ) from error
        normalized_usage = ProviderTokenUsage(
            input_tokens=prompt_tokens,
            cached_input_tokens=cache_hit_tokens,
            cache_write_input_tokens=0,
            output_tokens=completion_tokens,
            reasoning_tokens=0,
            total_tokens=total_tokens,
        )
        return ProviderGradeResult(
            provider_type=ProviderType.DEEPSEEK,
            requested_model=request.model,
            reported_model=reported_model,
            request_id=request_id,
            output_text=content,
            usage=normalized_usage,
            estimated_cost=self.estimate_cost(
                usage=normalized_usage,
                pricing=capabilities.pricing,
            ),
            raw_response=response.raw_body,
            raw_response_sha256=hashlib.sha256(response.raw_body).digest(),
            sent_schema_sha256=request.prompt.result_schema_hash,
        )
