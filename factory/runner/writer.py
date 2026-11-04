"""Serialize a rendered document bundle."""

from pathlib import Path

from factory.contract.lint import safe_path
from factory.runner.result import DocumentResult


def write_bundle(result: DocumentResult, folder: Path):
    """Serialize one result. Existing output is never modified here."""
    folder.mkdir(parents=True, exist_ok=True)
    for directory in ("pages", "images", "assets", "extra"):
        (folder / directory).mkdir(exist_ok=True)
    for name, model in {"content": result.content, "pagination": result.pagination,
                        "document": result.manifest, "spec": result.spec, "trace": result.trace}.items():
        (folder / f"{name}.json").write_text(model.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (folder / "style.css").write_text(result.style, encoding="utf-8")
    for name, html in result.pages.items():
        path = safe_path(folder, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
    for directory, files in (("assets", result.assets), ("extra", result.extra)):
        for name, content in files.items():
            path = safe_path(folder / directory, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
