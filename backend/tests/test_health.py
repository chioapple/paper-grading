"""健康检查接口测试。"""

from fastapi.testclient import TestClient

from app.api.health import get_readiness_probe
from app.config import Settings
from app.main import create_app
from tests.auth_settings import TEST_AUTH_SETTINGS


class StubReadinessProbe:
    """返回测试指定的数据库状态。"""

    def __init__(self, available: bool) -> None:
        self.available = available
        self.call_count = 0

    async def database_is_available(self) -> bool:
        self.call_count += 1
        return self.available


def build_test_settings() -> Settings:
    return Settings(
        APP_ENV="test",
        DATABASE_URL="postgresql+asyncpg://localhost:5432/paper_grading_test",
        **TEST_AUTH_SETTINGS,
    )


def test_live_does_not_check_external_dependencies() -> None:
    app = create_app(build_test_settings())
    probe = StubReadinessProbe(available=False)
    app.dependency_overrides[get_readiness_probe] = lambda: probe

    with TestClient(app) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "live"}
    assert probe.call_count == 0


def test_ready_reports_available_database() -> None:
    app = create_app(build_test_settings())
    probe = StubReadinessProbe(available=True)
    app.dependency_overrides[get_readiness_probe] = lambda: probe

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": {"status": "available"}},
    }
    assert probe.call_count == 1


def test_ready_reports_unavailable_database() -> None:
    app = create_app(build_test_settings())
    probe = StubReadinessProbe(available=False)
    app.dependency_overrides[get_readiness_probe] = lambda: probe

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"database": {"status": "unavailable"}},
    }
    assert probe.call_count == 1
