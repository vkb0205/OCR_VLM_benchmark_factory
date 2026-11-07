"""Registry of bundled academic-paper fonts with complete Vietnamese coverage."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import unicodedata
import struct

from factory.content.schema import font_coverage


FONT_DIR = Path(__file__).resolve().parents[2] / "designs" / "_fonts"


def vietnamese_codepoints() -> frozenset[int]:
    """Return the NFC code points used by the Vietnamese alphabet and tone marks."""
    bases = "aăâeêioôơuưyAĂÂEÊIOÔƠUƯY"
    tones = ("", "\u0300", "\u0301", "\u0303", "\u0309", "\u0323")
    chars = {"đ", "Đ"}
    for base in bases:
        for tone in tones:
            chars.add(unicodedata.normalize("NFC", base + tone))
    return frozenset(ord(char) for item in chars for char in item)


@dataclass(frozen=True)
class FontFamily:
    name: str
    file: str
    classification: str
    license_file: str
    vietnamese: bool
    source: str = "Google Fonts"

    @property
    def path(self) -> Path:
        return FONT_DIR / self.file


# The classification describes the family’s useful typographic role, not a
# preset: the design agent remains free to combine and use families as needed.
_FAMILIES = (
    FontFamily("Be Vietnam Pro", "BeVietnamPro-Regular.ttf", "sans", "bevietnampro-OFL.txt", True),
    FontFamily("Inter", "Inter-VF.ttf", "sans", "Inter-OFL.txt", True),
    FontFamily("Lora", "Lora-VF.ttf", "serif", "lora-OFL.txt", True),
    FontFamily("Merriweather", "Merriweather-VF.ttf", "serif", "Merriweather-OFL.txt", True),
    FontFamily("Montserrat", "Montserrat-VF.ttf", "sans", "Montserrat-OFL.txt", True),
    FontFamily("Noto Sans", "NotoSans-VF.ttf", "sans", "NotoSans-OFL.txt", True),
    FontFamily("Noto Serif", "NotoSerif-VF.ttf", "serif", "notoserif-OFL.txt", True),
    FontFamily("Source Serif 4", "SourceSerif4-VF.ttf", "serif", "SourceSerif4-OFL.txt", True),
    FontFamily("Alegreya", "alegreya-VF.ttf", "serif", "alegreya-OFL.txt", True),
    FontFamily("Aleo", "aleo-VF.ttf", "slab", "aleo-OFL.txt", True),
    FontFamily("Archivo", "archivo-VF.ttf", "sans", "archivo-OFL.txt", True),
    FontFamily("Barlow", "barlow-VF.ttf", "sans", "barlow-OFL.txt", True),
    FontFamily("Bitter", "bitter-VF.ttf", "slab", "bitter-OFL.txt", True),
    FontFamily("Cabin", "cabin-VF.ttf", "sans", "cabin-OFL.txt", True),
    FontFamily("Cormorant Garamond", "cormorantgaramond-VF.ttf", "serif", "cormorantgaramond-OFL.txt", True),
    FontFamily("Crimson Pro", "crimsonpro-VF.ttf", "serif", "crimsonpro-OFL.txt", True),
    FontFamily("EB Garamond", "ebgaramond-VF.ttf", "serif", "ebgaramond-OFL.txt", True),
    FontFamily("Fira Sans", "firasans-VF.ttf", "sans", "firasans-OFL.txt", True),
    FontFamily("IBM Plex Mono", "ibmplexmono-VF.ttf", "mono", "ibmplexmono-OFL.txt", True),
    FontFamily("IBM Plex Sans", "ibmplexsans-VF.ttf", "sans", "ibmplexsans-OFL.txt", True),
    FontFamily("Manrope", "manrope-VF.ttf", "sans", "manrope-OFL.txt", True),
    FontFamily("Newsreader", "newsreader-VF.ttf", "serif", "newsreader-OFL.txt", True),
    FontFamily("Open Sans", "opensans-VF.ttf", "sans", "opensans-OFL.txt", True),
    FontFamily("Oswald", "oswald-VF.ttf", "display", "oswald-OFL.txt", True),
    FontFamily("Public Sans", "publicsans-VF.ttf", "sans", "publicsans-OFL.txt", True),
    FontFamily("Roboto", "roboto-VF.ttf", "sans", "roboto-OFL.txt", True),
    FontFamily("Spectral", "spectral-VF.ttf", "serif", "spectral-OFL.txt", True),
    FontFamily("Work Sans", "worksans-VF.ttf", "sans", "worksans-OFL.txt", True),
    FontFamily("Andada Pro", "andadapro-VF.ttf", "serif", "andadapro-OFL.txt", True),
    FontFamily("Bricolage Grotesque", "bricolagegrotesque-VF.ttf", "display", "bricolagegrotesque-OFL.txt", True),
    FontFamily("Charis SIL", "charissil-VF.ttf", "serif", "charissil-OFL.txt", True),
    FontFamily("Fraunces", "fraunces-VF.ttf", "display", "fraunces-OFL.txt", True),
    FontFamily("JetBrains Mono", "jetbrainsmono-VF.ttf", "mono", "jetbrainsmono-OFL.txt", True),
    FontFamily("Lexend", "lexend-VF.ttf", "sans", "lexend-OFL.txt", True),
    FontFamily("Lilex", "lilex-VF.ttf", "mono", "lilex-OFL.txt", True),
)


@lru_cache(maxsize=128)
def _font_coverage(path: str, size: int, mtime_ns: int) -> frozenset[int]:
    del size, mtime_ns  # Included in the cache key so replaced assets are rechecked.
    return frozenset(font_coverage(Path(path)))


def check_vietnamese_coverage(font: FontFamily) -> tuple[bool, tuple[int, ...]]:
    """Check the actual cmap for every Vietnamese code point required by v3."""
    if not font.path.is_file():
        return False, tuple(sorted(vietnamese_codepoints()))
    stat = font.path.stat()
    found = _font_coverage(str(font.path.resolve()), stat.st_size, stat.st_mtime_ns)
    missing = tuple(sorted(vietnamese_codepoints() - found))
    return not missing, missing


def registry(*, validate: bool = True) -> tuple[FontFamily, ...]:
    """Return registered families, omitting absent or incomplete fonts by default."""
    if not validate:
        return _FAMILIES
    return tuple(font for font in _FAMILIES if check_vietnamese_coverage(font)[0])


def get_font(name: str) -> FontFamily:
    """Resolve a registry family name, requiring a valid Vietnamese cmap."""
    for font in registry():
        if font.name.casefold() == name.casefold():
            return font
    raise KeyError(f"unknown or unavailable Vietnamese-capable font family: {name!r}")


def family_records() -> tuple[dict[str, str | bool], ...]:
    """JSON-friendly list of the families that are safe to offer to the agent."""
    return tuple({"name": font.name, "file": font.file, "classification": font.classification,
                  "license_file": font.license_file, "vietnamese": True}
                 for font in registry())


def font_face_css(names) -> str:
    """Create local @font-face rules for agent-selected registry family names."""
    rules = []
    for name in dict.fromkeys(names):
        font = get_font(str(name))
        data = font.path.read_bytes()
        table_count = struct.unpack_from(">H", data, 4)[0]
        tables = {struct.unpack_from(">4s", data, 12 + index * 16)[0]:
                  struct.unpack_from(">I", data, 20 + index * 16)[0]
                  for index in range(table_count)}
        weight = "400"
        if b"fvar" in tables:
            fvar = tables[b"fvar"]
            _, _, data_offset, _, axis_count, axis_size, _, _ = struct.unpack_from(">8H", data, fvar)
            axes = fvar + data_offset
            for index in range(axis_count):
                axis = axes + index * axis_size
                tag = struct.unpack_from(">4s", data, axis)[0]
                if tag == b"wght":
                    minimum_fixed, maximum_fixed = struct.unpack_from(">ii", data, axis + 4)
                    minimum, maximum = minimum_fixed / 65536, maximum_fixed / 65536
                    weight = f"{minimum:g} {maximum:g}"
                    break
        elif b"OS/2" in tables:
            weight = str(struct.unpack_from(">H", data, tables[b"OS/2"] + 4)[0])
        rules.append(
            f'@font-face{{font-family:"{font.name}";src:url("assets/fonts/{font.file}") format("truetype");'
            f'font-weight:{weight};font-style:normal;font-display:block}}'
        )
    return "\n".join(rules)
