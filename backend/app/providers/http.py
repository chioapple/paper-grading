"""模型评分适配器共用的安全 HTTP 传输。"""

import json
import ssl
from decimal import Decimal

import certifi
from httpcore import AsyncConnectionPool, NetworkError, ProtocolError, TimeoutException

from app.providers.base import ProviderAdapterError, ProviderHttpResponse
from app.providers.connection import PinnedNetworkBackend, ValidatedBaseUrl

MAX_PROVIDER_RESPONSE_BYTES = 1_000_000
_SAFE_RESPONSE_HEADERS = {
    "content-type",
    "openai-request-id",
    "request-id",
    "retry-after",
    "x-request-id",
}


class HttpCoreProviderAdapterClient:
    """禁用代理和重定向，并把 TCP 固定到已验证公网 IP。"""

    async def get_json(
        self,
        *,
        target: ValidatedBaseUrl,
        url: str,
        headers: dict[str, str],
        timeout_seconds: Decimal,
    ) -> ProviderHttpResponse:
        return await self._request_json(
            method="GET",
            target=target,
            url=url,
            headers=headers,
            content=None,
            timeout_seconds=timeout_seconds,
        )

    async def post_json(
        self,
        *,
        target: ValidatedBaseUrl,
        url: str,
        headers: dict[str, str],
        json_body: dict[str, object],
        timeout_seconds: Decimal,
    ) -> ProviderHttpResponse:
        try:
            raw_request = json.dumps(
                json_body,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise ProviderAdapterError(
                "provider_request_invalid",
                "评分请求无法编码为 JSON",
            ) from error
        return await self._request_json(
            method="POST",
            target=target,
            url=url,
            headers=headers,
            content=raw_request,
            timeout_seconds=timeout_seconds,
        )

    async def _request_json(
        self,
        *,
        method: str,
        target: ValidatedBaseUrl,
        url: str,
        headers: dict[str, str],
        content: bytes | None,
        timeout_seconds: Decimal,
    ) -> ProviderHttpResponse:
        timeout = float(timeout_seconds)
        pool = AsyncConnectionPool(
            ssl_context=ssl.create_default_context(cafile=certifi.where()),
            max_connections=1,
            max_keepalive_connections=0,
            network_backend=PinnedNetworkBackend(target),
        )
        try:
            try:
                async with pool.stream(
                    method,
                    url,
                    headers=list(headers.items()),
                    content=content,
                    extensions={
                        "timeout": {
                            "connect": timeout,
                            "read": timeout,
                            "write": timeout,
                            "pool": timeout,
                        }
                    },
                ) as response:
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_stream():
                        size += len(chunk)
                        if size > MAX_PROVIDER_RESPONSE_BYTES:
                            raise ProviderAdapterError(
                                "provider_response_too_large",
                                "供应商评分响应超过安全上限",
                            )
                        chunks.append(chunk)
                    raw_body = b"".join(chunks)
                    try:
                        payload = json.loads(raw_body)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        payload = None
                    safe_headers = {
                        name.decode("latin-1").lower(): value.decode("latin-1")
                        for name, value in response.headers
                        if name.decode("latin-1").lower() in _SAFE_RESPONSE_HEADERS
                    }
                    return ProviderHttpResponse(
                        status_code=response.status,
                        json_body=payload,
                        raw_body=raw_body,
                        headers=safe_headers,
                    )
            except TimeoutException as error:
                raise ProviderAdapterError(
                    "provider_timeout",
                    "供应商评分请求超时",
                    retryable=True,
                ) from error
            except (NetworkError, ProtocolError) as error:
                raise ProviderAdapterError(
                    "provider_network_unavailable",
                    "无法安全连接供应商评分服务",
                    retryable=True,
                ) from error
        finally:
            await pool.aclose()
