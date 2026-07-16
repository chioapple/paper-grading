"""阶段七上传请求体上限测试。"""

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.http_limits import UploadBodyLimitMiddleware


def build_app(max_request_bytes: int = 8) -> FastAPI:
    application = FastAPI()
    application.add_middleware(
        UploadBodyLimitMiddleware,
        max_request_bytes=max_request_bytes,
    )

    @application.post("/assignments/{assignment_id}/submissions")
    async def upload(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    return application


def test_declared_oversized_upload_is_rejected_before_endpoint() -> None:
    with TestClient(build_app()) as client:
        response = client.post(
            "/assignments/44444444-4444-4444-8444-444444444444/submissions",
            content=b"123456789",
        )

    assert response.status_code == 413
    assert response.json() == {
        "detail": {"code": "file_too_large", "message": "上传请求超过 20MB 限制"}
    }


def test_chunked_oversized_upload_is_rejected_from_actual_received_bytes() -> None:
    def chunks() -> list[bytes]:
        return [b"1234", b"56789"]

    with TestClient(build_app()) as client:
        response = client.post(
            "/assignments/44444444-4444-4444-8444-444444444444/submissions",
            content=iter(chunks()),
            headers={"Transfer-Encoding": "chunked"},
        )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "file_too_large"
