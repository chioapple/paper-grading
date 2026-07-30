"""供应商连接测试契约。"""

from decimal import Decimal

import pytest

from app.domain.enums import ProviderType
from app.providers.connection import (
    ProviderBaseUrlPolicy,
    ProviderConnectionError,
    ProviderConnectionRequest,
    ProviderConnectionTester,
    ProviderHttpResponse,
)


@pytest.mark.anyio
async def test_deepseek_connection_lists_models_without_returning_the_key() -> None:
    class PublicResolver:
        async def resolve(self, host: str, port: int) -> tuple[str, ...]:
            assert (host, port) == ("api.deepseek.com", 443)
            return ("93.184.216.34",)

    class StubHttpClient:
        async def get_json(
            self,
            *,
            target: object,
            url: str,
            headers: dict[str, str],
            timeout_seconds: Decimal,
        ) -> ProviderHttpResponse:
            assert url == "https://api.deepseek.com/models"
            assert headers == {
                "Accept": "application/json",
                "Authorization": "Bearer stage-five-canary-key",
            }
            assert timeout_seconds == Decimal("60")
            return ProviderHttpResponse(
                status_code=200,
                json_body={
                    "object": "list",
                    "data": [
                        {"id": "deepseek-v4-flash"},
                        {"id": "deepseek-v4-pro"},
                    ],
                },
            )

    tester = ProviderConnectionTester(
        url_policy=ProviderBaseUrlPolicy(resolver=PublicResolver()),
        http_client=StubHttpClient(),
    )

    result = await tester.test(
        ProviderConnectionRequest(
            provider_type=ProviderType.DEEPSEEK,
            base_url="https://api.deepseek.com",
            api_key="stage-five-canary-key",  # pragma: allowlist secret
            default_model="deepseek-v4-flash",
            timeout_seconds=Decimal("60"),
        )
    )

    assert result.available_models == ["deepseek-v4-flash", "deepseek-v4-pro"]
    assert "stage-five-canary-key" not in result.model_dump_json()


@pytest.mark.anyio
async def test_wrong_provider_key_returns_a_stable_error_without_upstream_details() -> None:
    class PublicResolver:
        async def resolve(self, host: str, port: int) -> tuple[str, ...]:
            return ("93.184.216.34",)

    class RejectingHttpClient:
        async def get_json(self, **kwargs: object) -> ProviderHttpResponse:
            return ProviderHttpResponse(
                status_code=401,
                json_body={"error": {"message": "upstream included stage-five-canary-key"}},
            )

    tester = ProviderConnectionTester(
        url_policy=ProviderBaseUrlPolicy(resolver=PublicResolver()),
        http_client=RejectingHttpClient(),
    )

    with pytest.raises(ProviderConnectionError) as error:
        await tester.test(
            ProviderConnectionRequest(
                provider_type=ProviderType.DEEPSEEK,
                base_url="https://api.deepseek.com",
                api_key="stage-five-canary-key",  # pragma: allowlist secret
                default_model="deepseek-v4-flash",
                timeout_seconds=Decimal("60"),
            )
        )

    assert error.value.code == "provider_authentication_failed"
    assert "stage-five-canary-key" not in str(error.value)
    assert "upstream included" not in str(error.value)


@pytest.mark.anyio
async def test_gemini_connection_uses_its_native_models_contract() -> None:
    class PublicResolver:
        async def resolve(self, host: str, port: int) -> tuple[str, ...]:
            return ("142.250.72.202",)

    class StubHttpClient:
        async def get_json(
            self,
            *,
            target: object,
            url: str,
            headers: dict[str, str],
            timeout_seconds: Decimal,
        ) -> ProviderHttpResponse:
            assert url == "https://generativelanguage.googleapis.com/v1beta/models"
            assert headers == {
                "Accept": "application/json",
                "x-goog-api-key": "stage-five-canary-key",
            }
            return ProviderHttpResponse(
                status_code=200,
                json_body={"models": [{"name": "models/gemini-3.5-flash"}]},
            )

    result = await ProviderConnectionTester(
        url_policy=ProviderBaseUrlPolicy(resolver=PublicResolver()),
        http_client=StubHttpClient(),
    ).test(
        ProviderConnectionRequest(
            provider_type=ProviderType.GEMINI,
            base_url="https://generativelanguage.googleapis.com",
            api_key="stage-five-canary-key",  # pragma: allowlist secret
            default_model="gemini-3.5-flash",
            timeout_seconds=Decimal("30"),
        )
    )

    assert result.available_models == ["gemini-3.5-flash"]


@pytest.mark.anyio
async def test_anthropic_connection_uses_versioned_api_key_headers() -> None:
    class PublicResolver:
        async def resolve(self, host: str, port: int) -> tuple[str, ...]:
            return ("160.79.104.10",)

    class StubHttpClient:
        async def get_json(
            self,
            *,
            target: object,
            url: str,
            headers: dict[str, str],
            timeout_seconds: Decimal,
        ) -> ProviderHttpResponse:
            assert url == "https://api.anthropic.com/v1/models"
            assert headers == {
                "Accept": "application/json",
                "anthropic-version": "2023-06-01",
                "x-api-key": "stage-five-canary-key",
            }
            return ProviderHttpResponse(
                status_code=200,
                json_body={"data": [{"id": "claude-opus-4-20260701"}]},
            )

    result = await ProviderConnectionTester(
        url_policy=ProviderBaseUrlPolicy(resolver=PublicResolver()),
        http_client=StubHttpClient(),
    ).test(
        ProviderConnectionRequest(
            provider_type=ProviderType.ANTHROPIC,
            base_url="https://api.anthropic.com",
            api_key="stage-five-canary-key",  # pragma: allowlist secret
            default_model="claude-opus-4-20260701",
            timeout_seconds=Decimal("30"),
        )
    )

    assert result.available_models == ["claude-opus-4-20260701"]
