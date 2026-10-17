"""启动本地网站，并优先用 Google Chrome 打开。仅使用 Python 标准库。"""

from pathlib import Path
import os
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser


ROOT = Path(__file__).resolve().parent
URL = "http://127.0.0.1:8501/"


def is_ready() -> bool:
    """读取健康检查接口；服务启动前连接失败是正常情况。"""
    try:
        with urlopen(URL + "_stcore/health", timeout=1) as response:
            return response.status == 200 and response.read().strip() == b"ok"
    except (URLError, TimeoutError, OSError):
        return False


def open_browser() -> None:
    """从 Windows 常用安装位置寻找 Chrome，找不到时使用默认浏览器。"""
    for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(variable)
        if base:
            chrome = Path(base) / "Google/Chrome/Application/chrome.exe"
            if chrome.is_file():
                subprocess.Popen([str(chrome), URL])
                return
    webbrowser.open(URL)


def main() -> int:
    # 已有本地 Streamlit 服务时直接打开，避免重复启动同一个端口。
    if is_ready():
        print(f"Local website is running: {URL}")
        open_browser()
        return 0

    # 用当前虚拟环境启动服务，固定工作目录和本机监听地址。
    server = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py",
         "--server.address", "127.0.0.1", "--server.port", "8501",
         "--server.headless", "true"],
        cwd=ROOT,
    )
    try:
        for _ in range(90):
            if server.poll() is not None:
                print("Startup failed. Check the messages above (port 8501 may be busy).")
                return 1
            if is_ready():
                print(f"StudyPilot: {URL}\nKeep this window open. Press Ctrl+C to stop.")
                open_browser()
                server.wait()
                return 0 if server.returncode == 0 else 1
            time.sleep(0.5)
        print("Startup timed out. Check the messages above.")
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        # 只停止本脚本启动的子进程，不操作其它 Python 服务。
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


if __name__ == "__main__":
    raise SystemExit(main())
