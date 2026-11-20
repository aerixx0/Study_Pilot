"""StudyPilot's optional, loopback-only llama.cpp server."""

from contextlib import contextmanager
from http.client import HTTPConnection, HTTPException
import json
import logging
import os
import subprocess
import time

from .local_paths import LocalPaths

HOST = "127.0.0.1"
PORT = 11435
MODEL = "qwen3.5:4b"
BASE_URL = f"http://{HOST}:{PORT}/v1"
LOG = logging.getLogger(__name__)


def model_paths(paths):
    return (paths.home / "llama.cpp" / "llama-server.exe",
            paths.home / "models" / "Qwen3.5-4B-Q4_K_M.gguf")


def model_ready(paths=None):
    runtime, model = model_paths(paths or LocalPaths.current())
    if not runtime.is_file() or not model.is_file():
        return False
    connection = HTTPConnection(HOST, PORT, timeout=0.5)
    try:
        connection.request("GET", "/v1/models")
        response = connection.getresponse()
        if response.status != 200:
            return False
        models = json.loads(response.read(128_000)).get("data", [])
        return any(isinstance(item, dict) and item.get("id") == MODEL for item in models)
    except (OSError, HTTPException, ValueError, AttributeError, TypeError):
        return False
    finally:
        connection.close()


@contextmanager
def managed_inference(paths):
    """Start only the runtime installed by StudyPilot and stop only its process tree."""
    runtime, model = model_paths(paths)
    if (os.name != "nt" or not runtime.is_file() or not model.is_file()
            or os.getenv("STUDYPILOT_AI_ENABLED", "1") != "1"):
        yield
        return
    from .windows_process import KillOnCloseJob

    process = None
    job = None
    try:
        job = KillOnCloseJob()
        args = [runtime, "--host", HOST, "--port", str(PORT), "--model", model,
                "--alias", MODEL, "--jinja", "--ctx-size", "8192", "--parallel", "1",
                "--n-gpu-layers", "99", "--no-webui"]
        # The server's own HTTP diagnostics omit the request prompt at this level.
        with (paths.log.parent / "local-model.log").open("wb") as log:
            process = subprocess.Popen(args, cwd=runtime.parent,
                                       stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            job.attach(process.pid)
        except OSError:
            if process.poll() is None:
                process.kill()
            raise
        deadline = time.monotonic() + 12
        while process.poll() is None and time.monotonic() < deadline:
            if model_ready(paths):
                break
            time.sleep(0.15)
        else:
            LOG.warning("StudyPilot 本地模型没有就绪，请查看 local-model.log。")
    except OSError:
        LOG.warning("StudyPilot 无法启动本地模型，请查看 local-model.log。")
    try:
        yield
    finally:
        if job is not None:
            job.close()
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=3)
