"""只打包源码和文档，排除数据库、密钥、缓存和虚拟环境。"""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

workspace = Path(__file__).resolve().parents[1]
project = workspace / "outputs" / "StudyPilot"
archive = workspace / "outputs" / "StudyPilot-v0.2.0.zip"
excluded = {".venv", "venv", "__pycache__", "data", ".git", ".pytest_cache", "backups"}
with ZipFile(archive, "w", ZIP_DEFLATED) as package:
    for path in sorted(project.rglob("*")):
        relative = path.relative_to(project)
        if not path.is_file() or any(part in excluded for part in relative.parts):
            continue
        if path.name.startswith(".env") and path.name != ".env.example":
            continue
        if path.suffix in {".db", ".sqlite", ".sqlite3", ".log", ".pyc"}:
            continue
        package.write(path, Path("StudyPilot") / relative)
with ZipFile(archive) as package:
    assert package.testzip() is None
    assert "StudyPilot/app.py" in package.namelist()
    assert not any("/data/" in name or "/__pycache__/" in name for name in package.namelist())
    print(f"Packaged {len(package.namelist())} files, {archive.stat().st_size} bytes")
