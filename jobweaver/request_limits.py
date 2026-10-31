"""Count incoming ASGI body bytes before application parsing or dependencies run."""
import asyncio
import re

from starlette.responses import JSONResponse

GENERAL_BODY_BYTES = 16 * 1024 * 1024
PDF_BODY_BYTES = 40 * 1024 * 1024
RECEIVE_TIMEOUT_SECONDS = 30.0


def body_limit(path: str) -> int:
    if (re.fullmatch(r'/api/jobs/[^/]+/documents/(?:compile|finalize)', path)
            or re.fullmatch(r'/api/documents/[^/]+(?:/compile)?', path)):
        return PDF_BODY_BYTES
    return GENERAL_BODY_BYTES


class RequestBodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)

        async def reject(status, detail):
            await JSONResponse({'detail': detail}, status_code=status,
                               headers={'Connection': 'close'})(scope, receive, send)

        limit = body_limit(scope.get('path', ''))
        lengths = []
        for name, value in scope.get('headers', []):
            if name.lower() == b'content-encoding' and value.strip().lower() != b'identity':
                return await reject(415, 'Content-Encoding is unsupported; send an uncompressed body')
            if name.lower() == b'content-length':
                lengths.append(value)
        if lengths:
            if len(lengths) != 1 or not re.fullmatch(rb'[0-9]{1,20}', lengths[0]):
                return await reject(400, 'Invalid Content-Length')
            if int(lengths[0]) > limit:
                return await reject(413, 'Request body exceeds the endpoint byte limit')

        body_buffer = bytearray()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + RECEIVE_TIMEOUT_SECONDS
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return await reject(408, 'Request body receive deadline exceeded')
            try:
                message = await asyncio.wait_for(receive(), timeout=remaining)
            except TimeoutError:
                return await reject(408, 'Request body receive deadline exceeded')
            if message['type'] == 'http.disconnect':
                return
            if message['type'] != 'http.request':
                return await reject(400, 'Invalid request body stream')
            chunk = message.get('body', b'')
            if len(body_buffer) + len(chunk) > limit:
                return await reject(413, 'Request body exceeds the endpoint byte limit')
            body_buffer.extend(chunk)
            if not message.get('more_body', False):
                break
        body = bytes(body_buffer)
        body_buffer.clear()
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            return await receive()

        await self.app(scope, replay, send)
