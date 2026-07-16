"""Google Gemini GenerateContent 评分适配器。"""

import asyncio
import hashlib
from urllib.parse import quote

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


class GeminiAdapter(ProviderAdapterBase):
    """使用 GenerateContent 原生 Schema 输出执行评分。"""

    provider_type = ProviderType.GEMINI

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
        if request.provider_type is not ProviderType.GEMINI or (
            capabilities.structured_output != "json_schema"
            or capabilities.schema_dialect != "gemini"
            or capabilities.sampling_policy != "omit"
            or capabilities.thinking_policy != "omit"
            or capabilities.output_token_parameter != "max_output_tokens"
        ):
            raise ProviderAdapterError(
                "provider_capability_unsupported",
                "Gemini 模型能力快照不受当前适配器支持",
            )
        if request.prompt.messages[0].role != "system" or any(
            message.role != "user" for message in request.prompt.messages[1:]
        ):
            raise ProviderAdapterError(
                "provider_request_invalid",
                "Gemini 评分提示消息结构无效",
            )
        compiled_schema = compile_provider_schema(
            request.result_schema_json,
            dialect="gemini",
        )
        model_segment = quote(request.model, safe="")
        try:
            async with asyncio.timeout(float(request.timeout_seconds)):
                target = await self._url_policy.validate(ProviderType.GEMINI, request.base_url)
                response = await self._http_client.post_json(
                    target=target,
                    url=f"{target.value}/v1beta/models/{model_segment}:generateContent",
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "x-goog-api-key": request.api_key.get_secret_value(),
                    },
                    json_body={
                        "systemInstruction": {
                            "parts": [{"text": request.prompt.messages[0].content}],
                        },
                        "contents": [
                            {
                                "role": "user",
                                "parts": [{"text": message.content}],
                            }
                            for message in request.prompt.messages[1:]
                        ],
                        "generationConfig": {
                            "responseFormat": {
                                "text": {
                                    "mimeType": "application/json",
                                    "schema": compiled_schema.schema_body,
                                }
                            },
                            "maxOutputTokens": request.max_output_tokens,
                        },
                    },
                    timeout_seconds=request.timeout_seconds,
                )
        except TimeoutError as error:
            raise ProviderAdapterError(
                "provider_timeout",
                "Gemini 评分请求超时",
                retryable=True,
            ) from error
        raise_for_provider_status(response, provider_type=ProviderType.GEMINI)
        payload = response.json_body
        try:
            if not isinstance(payload, dict):
                raise TypeError
            prompt_feedback = payload.get("promptFeedback")
            if isinstance(prompt_feedback, dict) and prompt_feedback.get("blockReason"):
                raise ProviderAdapterError(
                    "provider_content_refused",
                    "Gemini 拒绝了该评分内容",
                    response=response,
                )
            request_id = payload["responseId"]
            reported_model = payload["modelVersion"]
            if not isinstance(request_id, str) or not request_id:
                raise TypeError
            if not isinstance(reported_model, str) or not reported_model:
                raise TypeError
            candidates = payload["candidates"]
            if not isinstance(candidates, list) or len(candidates) != 1:
                raise TypeError
            candidate = candidates[0]
            if not isinstance(candidate, dict) or candidate.get("index") != 0:
                raise TypeError
            finish_reason = candidate.get("finishReason")
            if finish_reason == "MAX_TOKENS":
                raise ProviderAdapterError(
                    "provider_output_truncated",
                    "Gemini 输出达到上限",
                    response=response,
                )
            if finish_reason in {
                "SAFETY",
                "RECITATION",
                "BLOCKLIST",
                "PROHIBITED_CONTENT",
                "SPII",
                "IMAGE_SAFETY",
                "IMAGE_PROHIBITED_CONTENT",
            }:
                raise ProviderAdapterError(
                    "provider_content_refused",
                    "Gemini 拒绝了该评分内容",
                    response=response,
                )
            if finish_reason != "STOP":
                raise TypeError
            content = candidate["content"]
            if not isinstance(content, dict) or content.get("role") != "model":
                raise TypeError
            parts = content["parts"]
            if not isinstance(parts, list) or len(parts) != 1 or not isinstance(parts[0], dict):
                raise TypeError
            output_text = parts[0]["text"]
            if not isinstance(output_text, str) or not output_text.strip():
                raise TypeError
            usage = payload["usageMetadata"]
            if not isinstance(usage, dict):
                raise TypeError
            input_tokens = usage["promptTokenCount"]
            cached_tokens = usage.get("cachedContentTokenCount", 0)
            candidate_tokens = usage["candidatesTokenCount"]
            reasoning_tokens = usage.get("thoughtsTokenCount", 0)
            total_tokens = usage["totalTokenCount"]
            if any(
                type(value) is not int or value < 0
                for value in (
                    input_tokens,
                    cached_tokens,
                    candidate_tokens,
                    reasoning_tokens,
                    total_tokens,
                )
            ):
                raise TypeError
            output_tokens = candidate_tokens + reasoning_tokens
            if total_tokens != input_tokens + output_tokens:
                raise TypeError
        except (KeyError, TypeError) as error:
            raise ProviderAdapterError(
                "provider_response_invalid",
                "Gemini 返回了无效评分响应",
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
            provider_type=ProviderType.GEMINI,
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
