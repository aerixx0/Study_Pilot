"""Manage the per-user Streamlit process without signaling unrelated PIDs."""

import asyncio
from contextlib import contextmanager
from http.client import HTTPConnection, HTTPException
import json
import logging
import os
import subprocess
import sys
from threading import Event, Thread
import time
from uuid import uuid4

from .local_paths import APP

HOST = "127.0.0.1"
DEFAULT_PORT = 8501
START_TIMEOUT = 60
STOP_TIMEOUT = 15


class ServiceError(ValueError):
    pass


@contextmanager
def file_lock(path, *, wait=0):
    """The OS releases this byte-range lock even when a process is killed."""
    if os.name == "nt":
        import msvcrt

        def acquire(file):
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)

        def release(file):
            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        def acquire(file):
            fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        def release(file):
            fcntl.flock(file.fileno(), fcntl.LOCK_UN)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as file:
        deadline = time.monotonic() + wait
        while True:
            try:
                file.seek(0)
                acquire(file)
                break
            except (BlockingIOError, PermissionError):
                if time.monotonic() >= deadline:
                    yield False
                    return
                time.sleep(0.1)
            except OSError as error:
                # Windows reports the locked range as EACCES via the C runtime.
                if os.name != "nt" or error.errno not in (13, 36):
                    raise
                if time.monotonic() >= deadline:
                    yield False
                    return
                time.sleep(0.1)
        try:
            yield True
        finally:
            release(file)


def url_for(port):
    return f"http://{HOST}:{port}/"


def healthy(port):
    conn = HTTPConnection(HOST, port, timeout=1)
    try:
        conn.request("GET", "/_stcore/health")
        response = conn.getresponse()
        return response.status == 200 and response.read(16).strip() == b"ok"
    except (OSError, HTTPException):
        return False
    finally:
        conn.close()


class LocalService:
    def __init__(self, paths):
        self.paths = paths
        self.state_file = paths.run / "service.json"
        self.worker_lock = paths.run / "worker.lock"

    def configured_port(self):
        try:
            settings = json.loads(self.paths.settings.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return None
        except ValueError:
            raise ServiceError(f"配置文件不是有效的 JSON：{self.paths.settings}") from None
        if not isinstance(settings, dict):
            raise ServiceError(f"配置文件须为 JSON 对象：{self.paths.settings}")
        port = settings.get("port")
        if port is not None and (type(port) is not int or not 1 <= port <= 65535):
            raise ServiceError(f"配置文件中的 port 须为 1–65535 的整数：{self.paths.settings}")
        return port

    @contextmanager
    def operation(self):
        with file_lock(self.paths.run / "commands.lock", wait=START_TIMEOUT + STOP_TIMEOUT) as owned:
            if not owned:
                raise ServiceError("另一项 StudyPilot 操作仍在进行，请稍后重试。")
            yield

    def state(self):
        with file_lock(self.worker_lock) as stopped:
            if stopped:
                return None
            try:
                state = json.loads(self.state_file.read_text(encoding="utf-8"))
                port = state["port"]
                if (uuid4_valid(state["id"]) and type(state["pid"]) is int
                        and (port is None or (type(port) is int and 1 <= port <= 65535))):
                    return state
            except (FileNotFoundError, PermissionError, ValueError, KeyError, TypeError):
                pass
            return {}

    def _ready(self, state):
        if not state or not state.get("port") or not healthy(state["port"]):
            return False
        return self.state() == state

    def status(self):
        with self.operation():
            state = self.state()
            if state is None:
                return "StudyPilot 未运行。", 1
            if self._ready(state):
                return f"StudyPilot 正在运行：{url_for(state['port'])}（PID {state['pid']}）", 0
            return f"StudyPilot 正在启动或暂时无响应。日志：{self.paths.log}", 2

    def start(self, port=None):
        with self.operation():
            previous = self.state()
            if previous is not None:
                if not self._ready(previous):
                    raise ServiceError("已有 StudyPilot 服务正在启动或无响应。请查看 status，或先停止服务。")
                if port is not None and previous["port"] != port:
                    raise ServiceError(f"StudyPilot 已在 {url_for(previous['port'])} 运行。请先停止，再更换端口。")
                return url_for(previous["port"])
            self.state_file.unlink(missing_ok=True)
            for request in self.paths.run.glob("stop-*.request"):
                request.unlink(missing_ok=True)

            log = self.paths.log
            log.parent.mkdir(parents=True, exist_ok=True)
            if log.exists():
                log.replace(log.with_suffix(".previous.log"))
            if not (APP / "app.py").is_file():
                raise ServiceError("找不到本地 Streamlit 应用。请重新安装，或通过可编辑模式安装源码。")
            instance = uuid4().hex
            argv = [sys.executable, "-B", "-X", "utf8", str(APP / "start_studypilot.py"), "_worker", instance]
            if port is not None:
                argv.append(str(port))
            options = ({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt"
                       else {"start_new_session": True})
            env = dict(os.environ, STUDYPILOT_HOME=str(self.paths.home),
                       STUDYPILOT_AUTH_DIR=str(self.paths.accounts), PYTHONDONTWRITEBYTECODE="1")
            with log.open("wb") as output:
                child = subprocess.Popen(argv, cwd=APP, env=env, stdin=subprocess.DEVNULL,
                                         stdout=output, stderr=subprocess.STDOUT, **options)
            ready = False
            try:
                deadline = time.monotonic() + START_TIMEOUT
                while time.monotonic() < deadline and child.poll() is None:
                    state = self.state()
                    if state and state["id"] == instance and self._ready(state):
                        ready = True
                        return url_for(state["port"])
                    time.sleep(0.15)
                raise ServiceError(f"StudyPilot 启动失败。请检查端口和日志：{log}")
            finally:
                if not ready and child.poll() is None:
                    child.kill()
                    child.wait()

    def stop(self):
        with self.operation():
            deadline = time.monotonic() + STOP_TIMEOUT
            while (state := self.state()) == {} and time.monotonic() < deadline:
                time.sleep(0.1)
            if state is None:
                return False
            if state:
                request = self.paths.run / f"stop-{state['id']}.request"
                request.touch()
                while time.monotonic() < deadline:
                    if self.state() is None:
                        request.unlink(missing_ok=True)
                        return True
                    time.sleep(0.1)
            raise ServiceError(f"StudyPilot 未能停止。日志：{self.paths.log}")

    def run_worker(self, instance, port):
        if not uuid4_valid(instance):
            return 2
        with file_lock(self.worker_lock) as owned:
            if not owned:
                return 2
            state = {"id": instance, "pid": os.getpid(), "port": None}
            temp = self.paths.run / f".{instance}.tmp"

            def publish():
                temp.write_text(json.dumps(state), encoding="utf-8")
                for attempt in range(5):
                    try:
                        temp.replace(self.state_file)
                        break
                    except PermissionError:
                        if attempt == 4:
                            raise
                        time.sleep(0.05)

            publish()
            request = self.paths.run / f"stop-{instance}.request"
            stop_requested, finished = Event(), Event()

            def monitor():
                while not finished.wait(0.15):
                    if request.exists():
                        stop_requested.set()
                        if not finished.wait(8):
                            os._exit(1)
                        return

            Thread(target=monitor, daemon=True).start()
            try:
                # Initialize the same local account store used by the UI and CLI before reporting ready.
                from .auth import LocalAuthStore
                from .local_inference import managed_inference

                auth = LocalAuthStore(self.paths.accounts)
                with managed_inference(self.paths):
                    asyncio.run(serve_local_browser(auth, port, state, publish, stop_requested))
                return 0
            finally:
                finished.set()
                temp.unlink(missing_ok=True)


def uuid4_valid(value):
    return isinstance(value, str) and len(value) == 32 and all(c in "0123456789abcdef" for c in value)


async def serve_local_browser(auth, port, state, publish, stop_requested):
    from .desktop_conversation import serve_conversation

    async with serve_conversation(auth):
        await serve_streamlit(port, state, publish, stop_requested)


async def serve_streamlit(port, state, publish, stop_requested):
    # Streamlit 1.65 is pinned. Use its managed Server so readiness comes from our own listener.
    from streamlit import config
    from streamlit.config_option import ConfigOption
    from streamlit.web import bootstrap
    from streamlit.web.server.server import Server

    script = str(APP / "app.py")
    bootstrap.load_config_options({
        "server.address": HOST, "server.port": DEFAULT_PORT if port is None else port,
        "server.headless": True, "server.baseUrlPath": "", "server.enableCORS": True,
        "server.corsAllowedOrigins": ("http://127.0.0.1",),
        "server.enableXsrfProtection": True, "server.fileWatcherType": "none",
        "browser.serverAddress": HOST, "browser.gatherUsageStats": False,
    })
    if port is None:
        # Use Streamlit's atomic bind and retry logic for the default port.
        config.set_option("server.port", DEFAULT_PORT, ConfigOption.DEFAULT_DEFINITION)
    bootstrap.prepare_streamlit_environment(script)
    server = Server(script, is_hello=False)
    await server.start()
    state["port"] = config.get_option("server.port")
    config.set_option("client.allowedOrigins", [url_for(state["port"]).rstrip("/")])
    publish()
    logging.getLogger(__name__).info("Ready on %s", url_for(state["port"]))

    async def shutdown():
        while not stop_requested.is_set():
            await asyncio.sleep(0.15)
        server.stop()

    watch = asyncio.create_task(shutdown())
    try:
        await server.stopped
    finally:
        watch.cancel()
