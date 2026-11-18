from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LoadResult:
    json_data: dict
    ink_files: list[Path]

    @property
    def has_source(self) -> bool:
        return len(self.ink_files) > 0


def load_story(path: str) -> LoadResult:
    """Load compiled Ink JSON from various input formats.

    Returns both the JSON data and any available .ink source file paths.
    """
    p = Path(path)

    if p.is_dir():
        ink_files = list(p.glob("**/*.ink"))
        return LoadResult(_compile_directory(p), ink_files)

    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")

    suffix = p.suffix.lower()

    if suffix == ".json" or p.name.endswith(".ink.json"):
        ink_dir = p.parent
        ink_files = list(ink_dir.glob("*.ink")) if ink_dir.exists() else []
        return LoadResult(_load_json(p), ink_files)
    elif suffix == ".tale":
        return LoadResult(_load_tale(p), [])
    elif suffix == ".otproject":
        return _load_otproject_with_source(p)
    elif suffix == ".ink":
        ink_dir = p.parent
        ink_files = list(ink_dir.glob("*.ink"))
        return LoadResult(_compile_ink(p), ink_files)
    else:
        return LoadResult(_load_json(p), [])


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f)
    if "inkVersion" not in data or "root" not in data:
        raise ValueError(f"Not a valid Ink JSON file: {path}")
    return data


def _load_tale(path: Path) -> dict:
    """Extract story/main.ink.json from a .tale ZIP archive."""
    with zipfile.ZipFile(path) as zf:
        candidates = [
            n for n in zf.namelist()
            if n.endswith("story/main.ink.json") or n.endswith("/main.ink.json")
        ]
        if not candidates:
            raise ValueError(f"No story/main.ink.json found in {path}")
        with zf.open(candidates[0]) as f:
            raw = f.read()
            if raw[0:3] == b"\xef\xbb\xbf":
                raw = raw[3:]
            return json.loads(raw)


def _load_otproject_with_source(path: Path) -> LoadResult:
    """Extract .ink files from .otproject, compile, return JSON + source paths."""
    _check_inklecate()
    tmpdir = tempfile.mkdtemp()
    ink_files = []
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if name.endswith(".ink"):
                target = Path(tmpdir) / Path(name).name
                with zf.open(name) as src, open(target, "wb") as dst:
                    dst.write(src.read())
                ink_files.append(target)

    if not ink_files:
        raise ValueError(f"No .ink files found in {path}")

    main_ink = Path(tmpdir) / "main.ink"
    if not main_ink.exists():
        if len(ink_files) == 1:
            main_ink = ink_files[0]
        else:
            raise ValueError(f"No main.ink in {path}, and multiple .ink files present")

    return LoadResult(_compile_ink(main_ink), ink_files)


def _load_otproject(path: Path) -> dict:
    """Extract .ink files from .otproject ZIP, compile with inklecate."""
    _check_inklecate()
    with tempfile.TemporaryDirectory() as tmpdir:
        with zipfile.ZipFile(path) as zf:
            ink_files = [n for n in zf.namelist() if n.endswith(".ink")]
            if not ink_files:
                raise ValueError(f"No .ink files found in {path}")
            for name in ink_files:
                target = Path(tmpdir) / Path(name).name
                with zf.open(name) as src, open(target, "wb") as dst:
                    dst.write(src.read())

        main_ink = Path(tmpdir) / "main.ink"
        if not main_ink.exists():
            ink_files_on_disk = list(Path(tmpdir).glob("*.ink"))
            if len(ink_files_on_disk) == 1:
                main_ink = ink_files_on_disk[0]
            else:
                raise ValueError(f"No main.ink found in {path}, and multiple .ink files present")

        return _compile_ink(main_ink)


def _compile_directory(directory: Path) -> dict:
    """Compile .ink files in a directory with inklecate."""
    main_ink = directory / "main.ink"
    if not main_ink.exists():
        ink_files = list(directory.glob("*.ink"))
        if len(ink_files) == 1:
            main_ink = ink_files[0]
        elif ink_files:
            raise ValueError(f"Multiple .ink files in {directory}; expected main.ink")
        else:
            raise FileNotFoundError(f"No .ink files found in {directory}")
    return _compile_ink(main_ink)


def _compile_ink(ink_path: Path) -> dict:
    """Compile a .ink file to JSON using inklecate."""
    _check_inklecate()
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        out_path = tmp.name
    try:
        subprocess.run(
            ["inklecate", "-o", out_path, str(ink_path)],
            check=True, capture_output=True, text=True,
        )
        return _load_json(Path(out_path))
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)


def _check_inklecate() -> None:
    if shutil.which("inklecate") is None:
        raise RuntimeError(
            "inklecate not found. Install it with: npm install -g inklecate\n"
            "Or download from: https://github.com/inkle/ink/releases"
        )
