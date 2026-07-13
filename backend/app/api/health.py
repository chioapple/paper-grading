"""服务存活与就绪检查接口。"""

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.readiness import ReadinessProbe

router = APIRouter(prefix="/health", tags=["health"])


class LiveResponse(BaseModel):
    """存活检查响应。"""

    status: Literal["live"]


class DependencyStatus(BaseModel):
    """单个外部依赖的状态。"""

    status: Literal["available", "unavailable"]


class ReadyResponse(BaseModel):
    """就绪检查响应。"""

    status: Literal["ready", "not_ready"]
    checks: dict[str, DependencyStatus]


def get_readiness_probe(request: Request) -> ReadinessProbe:
    """获取应用启动时创建的就绪检查器。"""

    return cast(ReadinessProbe, request.app.state.readiness_probe)


@router.get("/live", response_model=LiveResponse)
def live() -> LiveResponse:
    """只证明 HTTP 进程存活，不访问外部服务。"""

    return LiveResponse(status="live")


@router.get(
    "/ready",
    response_model=ReadyResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadyResponse}},
)
async def ready(
    probe: Annotated[ReadinessProbe, Depends(get_readiness_probe)],
) -> ReadyResponse | JSONResponse:
    """数据库可连接时才报告服务已就绪。"""

    if await probe.database_is_available():
        return ReadyResponse(
            status="ready",
            checks={"database": DependencyStatus(status="available")},
        )

    response = ReadyResponse(
        status="not_ready",
        checks={"database": DependencyStatus(status="unavailable")},
    )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=response.model_dump(mode="json"),
    )
