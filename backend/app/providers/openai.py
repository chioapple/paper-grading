"""OpenAI Responses API 评分适配器。"""

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


class OpenAIAdapter(ProviderAdapterBase):
    """使用 Responses API 的严格 Structured Outputs 执行评分。"""

    provider_type = ProviderType.OPENAI

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
        if request.provider_type is not ProviderType.OPENAI or (
            capabilities.structured_output != "json_schema"
            or capabilities.schema_dialect != "openai"
            or capabilities.sampling_policy != "omit"
            or capabilities.thinking_policy != "omit"
            or capabilities.output_token_parameter != "max_output_tokens"
        ):
            raise ProviderAdapterError(
                "provider_capability_unsupported",
                "OpenAI 模型能力快照不受当前适配器支持",
            )
        compiled_schema = compile_provider_schema(
            request.result_schema_json,
            dialect="openai",
        )
        try:
            async with asyncio.timeout(float(request.timeout_seconds)):
                target = await self._url_policy.validate(ProviderType.OPENAI, request.base_url)
                response = await self._http_client.post_json(
                    target=target,
                    url=f"{target.value}/responses",
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {request.api_key.get_secret_value()}",
                    },
                    json_body={
                        "model": request.model,
                        "input": [
                            {
                                "role": message.role,
                                "content": [{"type": "input_text", "text": message.content}],
                            }
                            for message in request.prompt.messages
                        ],
                        "text": {
                            "format": {
                                "type": "json_schema",
                                "name": "grade_result",
                                "strict": True,
                                "schema": compiled_schema.schema_body,
                            }
                        },
                        "max_output_tokens": request.max_output_tokens,
                        "store": False,
                        "stream": False,
                    },
                    timeout_seconds=request.timeout_seconds,
                )
        except TimeoutError as error:
            raise ProviderAdapterError(
                "provider_timeout",
                "OpenAI 评分请求超时",
                retryable=True,
            ) from error
        error_payload = (
            response.json_body.get("error") if isinstance(response.json_body, dict) else None
        )
        error_code = error_payload.get("code") if isinstance(error_payload, dict) else None
        if error_code in {"insufficient_quota", "billing_hard_limit_reached"}:
            raise ProviderAdapterError(
                "provider_quota_exhausted",
                "OpenAI 账户当前额度已用尽",
                response=response,
            )
        raise_for_provider_status(response, provider_type=ProviderType.OPENAI)
        payload = response.json_body
        try:
            if not isinstance(payload, dict) or payload.get("object") != "response":
                raise TypeError
            status = payload.get("status")
            if status == "incomplete":
                details = payload.get("incomplete_details")
                reason = details.get("reason") if isinstance(details, dict) else None
                if reason == "max_output_tokens":
                    raise ProviderAdapterError(
                        "provider_output_truncated",
                        "OpenAI 输出达到上限",
                        response=response,
                    )
                if reason == "content_filter":
                    raise ProviderAdapterError(
                        "provider_content_refused",
                        "OpenAI 拒绝了该评分内容",
                        response=response,
                    )
                raise TypeError
            if status != "completed":
                raise TypeError
            request_id = payload["id"]
            reported_model = payload["model"]
            if not isinstance(request_id, str) or not request_id:
                raise TypeError
            if not isinstance(reported_model, str) or not reported_model:
                raise TypeError
            output = payload["output"]
            if not isinstance(output, list) or len(output) != 1:
                raise TypeError
            message = output[0]
            if (
                not isinstance(message, dict)
                or message.get("type") != "message"
                or message.get("role") != "assistant"
                or message.get("status") != "completed"
            ):
                raise TypeError
            content_blocks = message["content"]
            if not isinstance(content_blocks, list) or len(content_blocks) != 1:
                raise TypeError
            content_block = content_blocks[0]
            if isinstance(content_block, dict) and content_block.get("type") == "refusal":
                raise ProviderAdapterError(
                    "provider_content_refused",
                    "OpenAI 拒绝了该评分内容",
                    response=response,
                )
            if not isinstance(content_block, dict) or content_block.get("type") != "output_text":
                raise TypeError
            output_text = content_block["text"]
            if not isinstance(output_text, str) or not output_text.strip():
                raise TypeError
            usage = payload["usage"]
            if not isinstance(usage, dict):
                raise TypeError
            input_tokens = usage["input_tokens"]
            output_tokens = usage["output_tokens"]
            total_tokens = usage["total_tokens"]
            input_details = usage["input_tokens_details"]
            output_details = usage["output_tokens_details"]
            if not isinstance(input_details, dict) or not isinstance(output_details, dict):
                raise TypeError
            cached_tokens = input_details["cached_tokens"]
            reasoning_tokens = output_details["reasoning_tokens"]
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
                "OpenAI 返回了无效评分响应",
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
            provider_type=ProviderType.OPENAI,
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
