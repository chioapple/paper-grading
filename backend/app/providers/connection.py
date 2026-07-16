"""供应商连接测试的 URL 与出站网络安全边界。"""

import asyncio
import json
import socket
import ssl
from dataclasses import dataclass
from decimal import Decimal
from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

import certifi
from httpcore import (
    AnyIOBackend,
    AsyncConnectionPool,
    AsyncNetworkBackend,
    AsyncNetworkStream,
    NetworkError,
    ProtocolError,
    TimeoutException,
)
from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ProviderType

OFFICIAL_BASE_URLS: dict[ProviderType, str] = {
    ProviderType.DEEPSEEK: "https://api.deepseek.com",
    ProviderType.KIMI: "https://api.moonshot.cn/v1",
    ProviderType.GLM: "https://open.bigmodel.cn/api/paas/v4",
    ProviderType.OPENAI: "https://api.openai.com/v1",
    ProviderType.ANTHROPIC: "https://api.anthropic.com",
    ProviderType.GEMINI: "https://generativelanguage.googleapis.com",
}


class ProviderUrlError(ValueError):
    """Base URL 不安全或无法解析。"""


class ProviderConnectionError(RuntimeError):
    """连接测试失败；只暴露稳定错误码，不透传上游正文。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class HostResolver(Protocol):
    """DNS 解析边界。"""

    async def resolve(self, host: str, port: int) -> tuple[str, ...]: ...


class SystemHostResolver:
    """使用系统解析器获取全部 TCP 地址。"""

    async def resolve(self, host: str, port: int) -> tuple[str, ...]:
        loop = asyncio.get_running_loop()
        try:
            results = await loop.getaddrinfo(
                host,
                port,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
            )
        except OSError as error:
            raise ProviderUrlError("Base URL 主机无法解析") from error
        addresses = tuple(dict.fromkeys(str(result[4][0]) for result in results))
        if not addresses:
            raise ProviderUrlError("Base URL 主机没有可用地址")
        return addresses


@dataclass(frozen=True, slots=True)
class ValidatedBaseUrl:
    """已规范化且 DNS 结果全部为公网地址的 Base URL。"""

    value: str
    host: str
    port: int
    addresses: tuple[str, ...]


def _is_forbidden_address(address: IPv4Address | IPv6Address) -> bool:
    mapped = address.ipv4_mapped if isinstance(address, IPv6Address) else None
    if mapped is not None:
        return _is_forbidden_address(mapped)
    return (
        not address.is_global
        or address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


class ProviderBaseUrlPolicy:
    """规范化 Base URL，并拒绝可能访问内网的目标。"""

    def __init__(self, resolver: HostResolver | None = None) -> None:
        self._resolver = resolver or SystemHostResolver()

    async def validate(
        self,
        provider_type: ProviderType,
        value: str,
    ) -> ValidatedBaseUrl:
        try:
            parsed = urlsplit(value.strip())
            port = parsed.port or 443
        except ValueError as error:
            raise ProviderUrlError("Base URL 格式无效") from error
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            raise ProviderUrlError("Base URL 必须使用 HTTPS")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ProviderUrlError("Base URL 不得包含凭据、查询参数或片段")

        host = parsed.hostname.encode("idna").decode("ascii").lower()
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ProviderUrlError("Base URL 端口无效")
        official_url = OFFICIAL_BASE_URLS.get(provider_type)
        normalized_path = parsed.path.rstrip("/")
        host_for_url = f"[{host}]" if ":" in host else host
        netloc = f"{host_for_url}:{port}" if port != 443 else host_for_url
        normalized = urlunsplit(("https", netloc, normalized_path, "", ""))
        if official_url is not None and normalized != official_url:
            raise ProviderUrlError("内置供应商必须使用官方 Base URL")

        addresses = await self._resolver.resolve(host, port)
        try:
            parsed_addresses = tuple(ip_address(address) for address in addresses)
        except ValueError as error:
            raise ProviderUrlError("Base URL DNS 返回了无效地址") from error
        if any(_is_forbidden_address(address) for address in parsed_addresses):
            raise ProviderUrlError("Base URL 只能解析到公网地址")
        return ValidatedBaseUrl(
            value=normalized,
            host=host,
            port=port,
            addresses=tuple(str(address) for address in parsed_addresses),
        )


class PinnedNetworkBackend(AsyncNetworkBackend):
    """把出站 TCP 连接固定到已经校验的公网 IP。"""

    def __init__(
        self,
        target: ValidatedBaseUrl,
        *,
        delegate: AsyncNetworkBackend | None = None,
    ) -> None:
        self._target = target
        self._delegate = delegate or AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> AsyncNetworkStream:
        if host.lower() != self._target.host or port != self._target.port:
            raise ProviderUrlError("出站连接目标与已验证 Base URL 不一致")
        last_error: NetworkError | TimeoutException | None = None
        for address in self._target.addresses:
            try:
                return await self._delegate.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (NetworkError, TimeoutException) as error:
                last_error = error
        assert last_error is not None
        raise last_error

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Any = None,
    ) -> AsyncNetworkStream:
        raise ProviderUrlError("供应商连接不允许 Unix Socket")

    async def sleep(self, seconds: float) -> None:
        await self._delegate.sleep(seconds)


class ProviderConnectionRequest(BaseModel):
    """执行一次无计费模型列表请求所需的配置快照。"""

    model_config = ConfigDict(extra="forbid")

    provider_type: ProviderType
    base_url: str
    api_key: str = Field(repr=False, min_length=1)
    default_model: str = Field(min_length=1)
    timeout_seconds: Decimal = Field(gt=0, le=300)


class ProviderHttpResponse(BaseModel):
    """HTTP 边界返回的最小安全响应。"""

    status_code: int
    json_body: object


class ProviderConnectionResult(BaseModel):
    """连接成功后可安全返回的模型信息。"""

    available_models: list[str]


class ProviderHttpClient(Protocol):
    """真实出站 HTTP 边界。"""

    async def get_json(
        self,
        *,
        target: ValidatedBaseUrl,
        url: str,
        headers: dict[str, str],
        timeout_seconds: Decimal,
    ) -> ProviderHttpResponse: ...


class ProviderConnectionTester:
    """按供应商协议验证凭证和默认模型。"""

    def __init__(
        self,
        *,
        url_policy: ProviderBaseUrlPolicy,
        http_client: ProviderHttpClient,
    ) -> None:
        self._url_policy = url_policy
        self._http_client = http_client

    @staticmethod
    def _request_parts(
        provider_type: ProviderType,
        base_url: str,
        api_key: str,
    ) -> tuple[str, dict[str, str]]:
        headers = {"Accept": "application/json"}
        if provider_type is ProviderType.ANTHROPIC:
            headers["anthropic-version"] = "2023-06-01"
            headers["x-api-key"] = api_key
            return f"{base_url}/v1/models", headers
        if provider_type is ProviderType.GEMINI:
            headers["x-goog-api-key"] = api_key
            return f"{base_url}/v1beta/models", headers
        headers["Authorization"] = f"Bearer {api_key}"
        return f"{base_url}/models", headers

    @staticmethod
    def _extract_models(provider_type: ProviderType, payload: object) -> list[str]:
        if not isinstance(payload, dict):
            raise ProviderConnectionError(
                "provider_response_invalid",
                "供应商返回了无效模型列表",
            )
        raw_models = payload.get("models" if provider_type is ProviderType.GEMINI else "data")
        if not isinstance(raw_models, list):
            raise ProviderConnectionError(
                "provider_response_invalid",
                "供应商返回了无效模型列表",
            )
        models: list[str] = []
        for item in raw_models:
            if not isinstance(item, dict):
                continue
            value = item.get("name" if provider_type is ProviderType.GEMINI else "id")
            if isinstance(value, str) and value:
                models.append(value.removeprefix("models/"))
        if not models:
            raise ProviderConnectionError(
                "provider_response_invalid",
                "供应商没有返回可用模型",
            )
        return models

    @staticmethod
    def _raise_for_status(status_code: int) -> None:
        if status_code in {401, 403}:
            raise ProviderConnectionError(
                "provider_authentication_failed",
                "供应商 API Key 无效或无权访问",
            )
        if status_code == 402:
            raise ProviderConnectionError(
                "provider_balance_unavailable",
                "供应商账户余额不足",
            )
        if status_code == 429:
            raise ProviderConnectionError(
                "provider_rate_limited",
                "供应商限制了连接测试频率",
            )
        if 300 <= status_code < 400:
            raise ProviderConnectionError(
                "provider_redirect_rejected",
                "供应商连接测试不允许重定向",
            )
        if status_code == 404:
            raise ProviderConnectionError(
                "provider_endpoint_invalid",
                "供应商 Base URL 不支持模型列表接口",
            )
        if status_code >= 500:
            raise ProviderConnectionError(
                "provider_unavailable",
                "供应商服务暂时不可用",
            )
        if status_code != 200:
            raise ProviderConnectionError(
                "provider_connection_failed",
                "供应商拒绝了连接测试",
            )

    async def test(self, request: ProviderConnectionRequest) -> ProviderConnectionResult:
        target = await self._url_policy.validate(request.provider_type, request.base_url)
        url, headers = self._request_parts(
            request.provider_type,
            target.value,
            request.api_key,
        )
        response = await self._http_client.get_json(
            target=target,
            url=url,
            headers=headers,
            timeout_seconds=request.timeout_seconds,
        )
        self._raise_for_status(response.status_code)
        models = self._extract_models(request.provider_type, response.json_body)
        if request.default_model not in models:
            raise ProviderConnectionError(
                "provider_model_unavailable",
                "默认模型不在供应商可用列表中",
            )
        return ProviderConnectionResult(available_models=models)


MAX_PROVIDER_RESPONSE_BYTES = 1_000_000


class HttpCoreProviderClient:
    """禁用代理和重定向、固定公网 IP 的真实连接测试客户端。"""

    async def get_json(
        self,
        *,
        target: ValidatedBaseUrl,
        url: str,
        headers: dict[str, str],
        timeout_seconds: Decimal,
    ) -> ProviderHttpResponse:
        timeout = float(timeout_seconds)
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        pool = AsyncConnectionPool(
            ssl_context=ssl_context,
            max_connections=1,
            max_keepalive_connections=0,
            network_backend=PinnedNetworkBackend(target),
        )
        try:
            try:
                async with pool.stream(
                    "GET",
                    url,
                    headers=list(headers.items()),
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
                            raise ProviderConnectionError(
                                "provider_response_too_large",
                                "供应商响应超过安全上限",
                            )
                        chunks.append(chunk)
                    raw_body = b"".join(chunks)
                    try:
                        json_body = json.loads(raw_body)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        json_body = {}
                    return ProviderHttpResponse(
                        status_code=response.status,
                        json_body=json_body,
                    )
            except TimeoutException as error:
                raise ProviderConnectionError(
                    "provider_connection_timeout",
                    "供应商连接测试超时",
                ) from error
            except (NetworkError, ProtocolError) as error:
                raise ProviderConnectionError(
                    "provider_unavailable",
                    "无法安全连接供应商",
                ) from error
        finally:
            await pool.aclose()
