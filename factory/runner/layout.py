"""Output tree contract for generated benchmark runs."""

from __future__ import annotations

import json
import re
from pathlib import Path


ALLOWED = {
    "out": {"documents", "failed", "runs", "index", ".tmp", "gallery.html"},
    "accepted": {
        "spec.json", "source_content.json", "document.json", "content.json",
        "pagination.json", "trace.json", "style.css", "design", "pages",
        "assets", "images", "extra",
    },
    "failed": {"spec.json", "trace.json", "problems.json", "replies", "design", "source_content.json"},
}

_DOC_ID = re.compile(r"^[a-z][a-z0-9_]*_\d{6}$")
_DOC_TYPE = re.compile(r"^[a-z][a-z0-9_]*$")
_PAGE = re.compile(r"^page_\d{3}\.html$")
_IMAGE = re.compile(r"^page_\d{3}\.png$")


def _unexpected_entries(folder: Path, allowed_files: set[str], allowed_dirs: set[str]) -> list[str]:
    problems = []
    if not folder.is_dir():
        return [f"missing directory: {folder}"]
    for entry in sorted(folder.iterdir()):
        if entry.is_dir():
            if entry.name not in allowed_dirs:
                problems.append(f"unexpected directory: {entry}")
        elif entry.name not in allowed_files:
            problems.append(f"unexpected file: {entry}")
    return problems


def _check_bundle(folder: Path, kind: str) -> list[str]:
    problems = []
    if kind == "accepted":
        required_files = {
            "spec.json", "source_content.json", "document.json", "content.json",
            "pagination.json", "trace.json", "style.css",
        }
        for name in sorted(required_files):
            if not (folder / name).is_file():
                problems.append(f"missing file: {folder / name}")
        problems.extend(_unexpected_entries(
            folder,
            {"spec.json", "source_content.json", "document.json", "content.json",
             "pagination.json", "trace.json", "style.css"},
            {"design", "pages", "assets", "images", "extra"},
        ))
        expected_dirs = {
            "design": {"design_spec.json", "design.html"},
            "pages": None,
            "images": None,
            "extra": None,
        }
        for name, files in expected_dirs.items():
            child = folder / name
            if not child.is_dir():
                problems.append(f"missing directory: {child}")
                continue
            if name == "pages":
                for item in child.iterdir():
                    if not item.is_file() or not _PAGE.fullmatch(item.name):
                        problems.append(f"unexpected entry: {item}")
            elif name == "images":
                for item in child.iterdir():
                    if not item.is_file() or not _IMAGE.fullmatch(item.name):
                        problems.append(f"unexpected entry: {item}")
            elif name == "extra":
                entries = list(child.iterdir())
                actual = {item.name for item in entries}
                allowed = {"statements.json", "boxes.json", "lint.json"}
                required = {"statements.json"}
                manifest = json.loads((folder / "document.json").read_text(encoding="utf-8"))
                if manifest.get("contract_version") == "0.3.0":
                    required.update({"boxes.json", "lint.json"})
                if actual - allowed:
                    problems.append(f"unexpected entries in {child}: {sorted(actual - allowed)}")
                if required - actual:
                    problems.append(f"missing entries in {child}: {sorted(required - actual)}")
                if any(not item.is_file() for item in entries):
                    problems.append(f"expected files in {child}")
            elif files is not None:
                entries = list(child.iterdir())
                actual = {item.name for item in entries}
                if actual != files:
                    problems.append(f"unexpected entries in {child}: {sorted(actual ^ files)}")
                if any(not item.is_file() for item in entries):
                    problems.append(f"expected files in {child}")
        assets = folder / "assets"
        if not assets.is_dir():
            problems.append(f"missing directory: {assets}")
    else:
        for name in ("spec.json", "trace.json", "problems.json"):
            if not (folder / name).is_file():
                problems.append(f"missing file: {folder / name}")
        problems.extend(_unexpected_entries(
            folder, {"spec.json", "trace.json", "problems.json", "source_content.json"},
            {"replies", "design"}
        ))
        replies = folder / "replies"
        if replies.exists() and replies.is_dir():
            entries = list(replies.iterdir())
            actual = {item.name for item in entries}
            expected = {"element_reply.txt", "design_reply.txt"} & actual
            if not actual or actual != expected or any(not item.is_file() for item in entries):
                problems.append(f"unexpected entries in {replies}: {sorted(actual - expected)}")
        design = folder / "design"
        if design.exists() and design.is_dir():
            actual = {item.name for item in design.iterdir()}
            if actual != {"design.html"} or any(not item.is_file() for item in design.iterdir()):
                problems.append(f"unexpected entries in {design}: {sorted(actual ^ {'design.html'})}")
    return problems


def check_tree(out: Path) -> list[str]:
    """Return violations of the generation output contract."""
    out = Path(out)
    problems = _unexpected_entries(out, {"gallery.html"}, {"documents", "failed", "runs", "index", ".tmp"})
    for name in ("documents", "failed", "runs", "index", ".tmp"):
        if not (out / name).is_dir():
            problems.append(f"missing directory: {out / name}")
    if not (out / "gallery.html").is_file():
        problems.append(f"missing file: {out / 'gallery.html'}")
    for name, expected in (("index", {"documents.jsonl", "designs.jsonl", "languages.json"}),):
        folder = out / name
        if folder.is_dir():
            entries = list(folder.iterdir())
            actual = {item.name for item in entries}
            if actual != expected:
                problems.append(f"unexpected entries in {folder}: {sorted(actual ^ expected)}")
            if any(not item.is_file() for item in entries):
                problems.append(f"expected files in {folder}")
        else:
            problems.append(f"missing directory: {folder}")
    runs = out / "runs"
    if runs.is_dir():
        for run in sorted(runs.iterdir()):
            if (not run.is_dir() or {item.name for item in run.iterdir()} != {"run.json"}
                    or not (run / "run.json").is_file()):
                problems.append(f"unexpected run contents: {run}")
    for root_name, kind in (("documents", "accepted"), ("failed", "failed")):
        root = out / root_name
        if not root.is_dir():
            continue
        for type_dir in sorted(root.iterdir()):
            if not type_dir.is_dir() or not _DOC_TYPE.fullmatch(type_dir.name):
                problems.append(f"unexpected entry: {type_dir}")
                continue
            for bundle in sorted(type_dir.iterdir()):
                if (not bundle.is_dir() or not _DOC_ID.fullmatch(bundle.name)
                        or not bundle.name.startswith(type_dir.name + "_")):
                    problems.append(f"unexpected bundle path: {bundle}")
                    continue
                problems.extend(_check_bundle(bundle, kind))
    temp = out / ".tmp"
    if temp.is_dir() and any(temp.rglob("*")):
        problems.append(f"{temp} is not empty")
    return problems
