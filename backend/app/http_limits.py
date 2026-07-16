"""在表单解析和临时文件写入前限制论文上传请求体。"""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_SUBMISSION_FILE_BYTES = 20 * 1024 * 1024
MAX_MULTIPART_OVERHEAD_BYTES = 64 * 1024
MAX_SUBMISSION_REQUEST_BYTES = MAX_SUBMISSION_FILE_BYTES + MAX_MULTIPART_OVERHEAD_BYTES


class UploadRequestTooLargeError(RuntimeError):
    """实际接收的上传请求体超过上限。"""


def _is_submission_upload(scope: Scope) -> bool:
    if scope["type"] != "http" or scope.get("method") != "POST":
        return False
    segments = [segment for segment in scope.get("path", "").split("/") if segment]
    return len(segments) == 3 and segments[0] == "assignments" and segments[2] == "submissions"


class UploadBodyLimitMiddleware:
    """同时限制 Content-Length 和 chunked 请求的实际接收字节数。"""

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_request_bytes: int = MAX_SUBMISSION_REQUEST_BYTES,
    ) -> None:
        self._app = app
        self._max_request_bytes = max_request_bytes

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            status_code=413,
            content={
                "detail": {
                    "code": "file_too_large",
                    "message": "上传请求超过 20MB 限制",
                }
            },
        )
        await response(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not _is_submission_upload(scope):
            await self._app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                declared_bytes = int(content_length)
            except ValueError:
                declared_bytes = 0
            if declared_bytes > self._max_request_bytes:
                await self._reject(scope, receive, send)
                return

        received_bytes = 0
        request_too_large = False
        rejection_sent = False

        async def receive_with_limit() -> Message:
            nonlocal received_bytes, request_too_large
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self._max_request_bytes:
                    request_too_large = True
                    raise UploadRequestTooLargeError
            return message

        async def send_with_limit(message: Message) -> None:
            nonlocal rejection_sent
            if not request_too_large:
                await send(message)
                return
            if not rejection_sent:
                rejection_sent = True
                await self._reject(scope, receive, send)

        try:
            await self._app(scope, receive_with_limit, send_with_limit)
        except UploadRequestTooLargeError:
            if not rejection_sent:
                await self._reject(scope, receive, send)
