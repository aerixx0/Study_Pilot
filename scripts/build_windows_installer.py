"""Build the offline Windows x64 installer with embedded CPython and Inno Setup 6."""

import argparse
import ensurepip
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib.request import urlretrieve
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "python-ai-agent-ai-agent-studypilot" / "outputs" / "StudyPilot"
WINDOWS = ROOT / "scripts" / "windows"
VERSION = "3.13.14"
PYTHON_SHA256 = "90b4e5b9898b72d744650524bff92377c367f44bd5fbd09e3148656c080ad907"
NAME = "StudyPilot-Windows-x64-Setup.exe"


def checksum(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def stage_app(destination):
    destination.mkdir()
    for filename in ("app.py", "start_studypilot.py", "LICENSE"):
        shutil.copy2(APP / filename, destination)
    # Allowlist runtime source and assets. Never stage databases, credentials or checkout caches.
    assets = destination / "assets"
    assets.mkdir()
    for filename in ("learning-map.svg", "style.css", "theme-switcher.html", "theme-switcher.js"):
        shutil.copy2(APP / "assets" / filename, assets)
    public = destination / "public"
    public.mkdir()
    for filename in ("index.html", "study.css", "study.js", "motion.js", "workflow.js", "i18n.js"):
        shutil.copy2(APP / "public" / filename, public)
    package = destination / "studypilot"
    package.mkdir()
    for module in (APP / "studypilot").glob("*.py"):
        shutil.copy2(module, package)
    (destination / ".streamlit").mkdir()
    shutil.copy2(APP / ".streamlit" / "config.toml", destination / ".streamlit")


def stage_runtime(runtime, scratch, archive, wheelhouse):
    if archive is None:
        archive = scratch / f"python-{VERSION}-embed-amd64.zip"
        urlretrieve(f"https://www.python.org/ftp/python/{VERSION}/{archive.name}", archive)
    if checksum(archive) != PYTHON_SHA256:
        raise ValueError("The embedded Python archive did not match python.org's SHA-256.")
    with ZipFile(archive) as bundle:
        bundle.extractall(runtime)
    pth = next(runtime.glob("python*._pth"))
    pth.write_text(f"python313.zip\n.\nLib/site-packages\n../app\n", encoding="ascii")
    wheel = next(Path(ensurepip.__file__).with_name("_bundled").glob("pip-*.whl"))
    # The build host supplies pip only for the build. Resolve wheels with the shipped interpreter.
    pip_entry = "import sys; sys.path.insert(0, sys.argv.pop(1)); from pip._internal.cli.main import main; sys.exit(main())"
    python = runtime / "python.exe"
    index = (["--no-index", "--find-links", wheelhouse] if wheelhouse is not None
             else ["--index-url", "https://pypi.org/simple"])
    subprocess.run([python, "-B", "-c", pip_entry, wheel, "--isolated", "install",
                    "--disable-pip-version-check", "--only-binary=:all:", "--no-compile",
                    *index,
                    "--target", runtime / "Lib/site-packages", "-r", APP / "requirements-windows.txt"],
                   check=True)
    # pip may emit console wrappers with build-time interpreter paths. Our own CLI is relocatable.
    scripts = runtime / "Lib/site-packages/bin"
    if scripts.is_dir():
        if scripts.resolve().parent != (runtime / "Lib/site-packages").resolve():
            raise ValueError("Unexpected staging path.")
        shutil.rmtree(scripts)
    subprocess.run([python, "-B", "-c", "import fastapi, streamlit, sqlite3, ssl, pyarrow, pandas, studypilot.cli, studypilot.web"],
                   check=True)


def build(args):
    if sys.platform != "win32":
        raise SystemExit("Build this installer on Windows.")
    root = Path(os.environ["WINDIR"])
    compiler = root / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="studypilot-build-", dir=args.work_dir) as staging:
        scratch = Path(staging)
        payload = scratch / "payload"
        payload.mkdir()
        stage_app(payload / "app")
        stage_runtime(payload / "runtime", scratch, args.python_zip, args.wheelhouse)
        (payload / "bin").mkdir()
        subprocess.run([compiler, "/nologo", "/target:exe", "/platform:x64", "/optimize+",
                        f"/out:{payload / 'bin' / 'studypilot.exe'}", WINDOWS / "Launcher.cs"], check=True)
        subprocess.run([args.iscc, "/Q", f"/DPayload={payload}", f"/O{args.output_dir.resolve()}",
                        WINDOWS / "StudyPilot.iss"], check=True)
    installer = args.output_dir / NAME
    installer.with_name(NAME + ".sha256").write_text(f"{checksum(installer)}  {NAME}\n", encoding="ascii")
    print(installer.resolve())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iscc", required=True, type=lambda path: Path(path).resolve())
    parser.add_argument("--python-zip", type=Path, help="Optional cached official x64 embedded ZIP")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "verification")
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--wheelhouse", type=Path, help="Install locked wheels from this offline directory")
    build(parser.parse_args())
