"""Load the versioned category and attribute vocabulary."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


class Taxonomy:
    """Category sets and string-valued attributes from the shared YAML file."""

    def __init__(self, path: Path | None = None):
        self.data = yaml.safe_load((path or ROOT / "configs/taxonomy.yaml").read_text(encoding="utf-8"))
        self.version = self.data["version"]
        self.text = set(self.data["categories"]["text"]) | {"handwriting"}
        self.spans = set(self.data["categories"]["span"])
        self.blocks = set().union(*(set(v) for k, v in self.data["categories"].items() if k != "span"))

    def valid_attribute(self, scope: str, key: str, value: str) -> bool:
        """YAML booleans have lowercase HTML spellings."""
        values = self.data[f"{scope}_attributes"].get(key, [])
        return value in {str(v).lower() if isinstance(v, bool) else str(v) for v in values}
