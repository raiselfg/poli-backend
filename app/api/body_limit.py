import tempfile

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from app.api.files import MAX_FILE_SIZE, MAX_REQUEST_FILE_SIZE, MAX_REQUEST_FILES

MULTIPART_OVERHEAD = 1024 * 1024
UPLOAD_LIMITS = {
    "/api/v1/requests": MAX_REQUEST_FILES * MAX_REQUEST_FILE_SIZE + MULTIPART_OVERHEAD,
    "/api/v1/admin/media": MAX_FILE_SIZE + MULTIPART_OVERHEAD,
}


class UploadBodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        limit = UPLOAD_LIMITS.get(scope["path"])
        if limit is None:
            await self.app(scope, receive, send)
            return
        with tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as body:
            size = 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                size += len(chunk)
                if size > limit:
                    response = JSONResponse(
                        status_code=413, content={"detail": "Request too large"}
                    )
                    await response(scope, receive, send)
                    return
                await run_in_threadpool(body.write, chunk)
                if not message.get("more_body", False):
                    break
            body.seek(0)

            async def replay():
                chunk = await run_in_threadpool(body.read, 64 * 1024)
                return {"type": "http.request", "body": chunk, "more_body": bool(chunk)}

            await self.app(scope, replay, send)
