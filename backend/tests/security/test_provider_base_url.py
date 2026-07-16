"""供应商 Base URL 安全契约测试。"""

import pytest
from httpcore import NetworkError

from app.domain.enums import ProviderType
from app.providers.connection import (
    PinnedNetworkBackend,
    ProviderBaseUrlPolicy,
    ProviderUrlError,
)


@pytest.mark.anyio
async def test_custom_base_url_rejects_mixed_public_and_loopback_dns_results() -> None:
    class MixedResolver:
        async def resolve(self, host: str, port: int) -> tuple[str, ...]:
            assert (host, port) == ("models.example.com", 443)
            return ("93.184.216.34", "127.0.0.1")

    policy = ProviderBaseUrlPolicy(resolver=MixedResolver())

    with pytest.raises(ProviderUrlError, match="公网"):
        await policy.validate(
            ProviderType.OPENAI_COMPATIBLE,
            "https://models.example.com/v1",
        )


@pytest.mark.anyio
async def test_custom_base_url_accepts_https_with_only_public_addresses() -> None:
    class PublicResolver:
        async def resolve(self, host: str, port: int) -> tuple[str, ...]:
            return ("93.184.216.34",)

    validated = await ProviderBaseUrlPolicy(resolver=PublicResolver()).validate(
        ProviderType.OPENAI_COMPATIBLE,
        "https://Models.Example.com:443/v1/",
    )

    assert validated.value == "https://models.example.com/v1"
    assert validated.addresses == ("93.184.216.34",)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "blocked_address",
    ["10.0.0.1", "169.254.1.2", "224.0.0.1", "100.64.0.1", "::1", "fc00::1", "fe80::1"],
)
async def test_custom_base_url_rejects_every_non_public_address(
    blocked_address: str,
) -> None:
    class BlockedResolver:
        async def resolve(self, host: str, port: int) -> tuple[str, ...]:
            return (blocked_address,)

    with pytest.raises(ProviderUrlError, match="公网"):
        await ProviderBaseUrlPolicy(resolver=BlockedResolver()).validate(
            ProviderType.OPENAI_COMPATIBLE,
            "https://models.example.com/v1",
        )


@pytest.mark.anyio
async def test_connection_uses_the_validated_ip_instead_of_resolving_the_hostname_again() -> None:
    class PublicResolver:
        async def resolve(self, host: str, port: int) -> tuple[str, ...]:
            return ("93.184.216.34",)

    class RecordingBackend:
        def __init__(self) -> None:
            self.destination: tuple[str, int] | None = None

        async def connect_tcp(
            self,
            host: str,
            port: int,
            timeout: float | None = None,
            local_address: str | None = None,
            socket_options: object = None,
        ) -> object:
            self.destination = (host, port)
            return object()

    target = await ProviderBaseUrlPolicy(resolver=PublicResolver()).validate(
        ProviderType.OPENAI_COMPATIBLE,
        "https://models.example.com/v1",
    )
    delegate = RecordingBackend()

    await PinnedNetworkBackend(target, delegate=delegate).connect_tcp(  # type: ignore[arg-type]
        "models.example.com",
        443,
    )

    assert delegate.destination == ("93.184.216.34", 443)


@pytest.mark.anyio
async def test_connection_tries_each_validated_public_ip_before_failing() -> None:
    class PublicResolver:
        async def resolve(self, host: str, port: int) -> tuple[str, ...]:
            return ("93.184.216.34", "93.184.216.35")

    class FailoverBackend:
        def __init__(self) -> None:
            self.destinations: list[tuple[str, int]] = []

        async def connect_tcp(
            self,
            host: str,
            port: int,
            timeout: float | None = None,
            local_address: str | None = None,
            socket_options: object = None,
        ) -> object:
            self.destinations.append((host, port))
            if host == "93.184.216.34":
                raise NetworkError("first address unavailable")
            return object()

    target = await ProviderBaseUrlPolicy(resolver=PublicResolver()).validate(
        ProviderType.OPENAI_COMPATIBLE,
        "https://models.example.com/v1",
    )
    delegate = FailoverBackend()

    await PinnedNetworkBackend(target, delegate=delegate).connect_tcp(  # type: ignore[arg-type]
        "models.example.com",
        443,
    )

    assert delegate.destinations == [
        ("93.184.216.34", 443),
        ("93.184.216.35", 443),
    ]
