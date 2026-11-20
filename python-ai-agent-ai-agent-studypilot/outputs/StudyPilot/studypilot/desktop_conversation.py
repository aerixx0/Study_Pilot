"""Expose the actual Web conversation UI beside the desktop Streamlit app."""

import asyncio
from contextlib import asynccontextmanager
from secrets import token_urlsafe
import socket
from threading import Lock
from time import monotonic
from urllib.parse import urlencode

HOST = "127.0.0.1"
TICKET_TTL = 60
MAX_TICKETS = 128
_conversation = None


class ConversationHandoff:
    def __init__(self, port):
        self.url = f"http://{HOST}:{port}"
        self._tickets = {}
        self._lock = Lock()

    def issue(self, session):
        if not isinstance(session, str) or not session:
            return None
        with self._lock:
            now = monotonic()
            self._tickets = {key: value for key, value in self._tickets.items() if value[1] > now}
            if len(self._tickets) >= MAX_TICKETS:
                self._tickets.pop(next(iter(self._tickets)))
            ticket = token_urlsafe(32)
            self._tickets[ticket] = (session, now + TICKET_TTL)
        return f"{self.url}/desktop-login?{urlencode({'ticket': ticket})}"

    def redeem(self, ticket):
        with self._lock:
            value = self._tickets.pop(ticket, None)
        return value[0] if value and value[1] > monotonic() else None


def conversation_link(session):
    return _conversation.issue(session) if _conversation is not None else None


@asynccontextmanager
async def serve_conversation(auth):
    import uvicorn
    from .web import create_app

    global _conversation
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind((HOST, 0))
        port = listener.getsockname()[1]
        handoff = ConversationHandoff(port)
        web = create_app(lambda: auth, desktop_handoff=handoff)
        config = uvicorn.Config(web, host=HOST, port=port, access_log=False, proxy_headers=False,
                                timeout_graceful_shutdown=2)
        server = uvicorn.Server(config)
        task = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    if task.done():
                        task.result()
                        raise RuntimeError("StudyPilot conversation server failed to start.")
                    await asyncio.sleep(0.025)
            _conversation = handoff
            yield
        finally:
            _conversation = None
            server.should_exit = True
            await task
