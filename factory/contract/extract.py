"""Parsed-HTML ground truth extraction (CONTRACT.md section 3.7)."""

from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser
import re
import unicodedata

VOID = {"br", "img", "meta", "link", "input", "hr", "source", "wbr", "area", "base", "embed", "col", "param", "track"}
BOUNDARIES = {"p", "div", "section", "article", "header", "footer", "h1", "h2", "h3", "li", "ul", "ol", "blockquote", "pre"}


@dataclass
class Element:
    """Small HTML tree; parent pointers support ancestry checks."""

    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list = field(default_factory=list)
    parent: "Element | None" = field(default=None, repr=False)
    hidden: bool = False

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Element):
                yield from child.walk()


class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Element("document")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Element(tag, dict((k, v or "") for k, v in attrs), parent=self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def matches(node, selector):
    """Match simple tag/class/id selectors, including descendant selectors."""
    bits = selector.strip().split()
    if not bits:
        return False
    simple = bits[-1]
    tag = re.match(r"^[\w-]+|^\*", simple)
    if tag and tag[0] not in {"*", node.tag}:
        return False
    for prefix, value in re.findall(r"([.#])([\w-]+)", simple):
        if prefix == "." and value not in node.attrs.get("class", "").split():
            return False
        if prefix == "#" and value != node.attrs.get("id"):
            return False
    if any(c in simple for c in ":[>+~"):
        return False
    if len(bits) == 1:
        return True
    parent = node.parent
    while parent:
        if matches(parent, " ".join(bits[:-1])):
            return True
        parent = parent.parent
    return False


def parse_html(html: str) -> Element:
    parser = Parser()
    parser.feed(html)
    root = parser.root
    rules = []
    for style in (n for n in root.walk() if n.tag == "style"):
        css = "".join(c for c in style.children if isinstance(c, str))
        for selectors, declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            if re.search(r"(?:display|visibility)\s*:", declarations):
                rules.extend((s.strip(), declarations) for s in selectors.split(","))
    for node in root.walk():
        declarations = ";".join(d for s, d in rules if matches(node, s)) + ";" + node.attrs.get("style", "")
        properties = dict((k.strip().lower(), v.strip().lower().replace("!important", "").strip())
                          for k, v in re.findall(r"(display|visibility)\s*:\s*([^;]+)", declarations))
        node.hidden = ("hidden" in node.attrs or properties.get("display") == "none"
                       or properties.get("visibility") in {"hidden", "collapse"}
                       or bool(node.parent and node.parent.hidden))
    return root


def normalize(text: str) -> str:
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in text.splitlines()]
    return unicodedata.normalize("NFC", "\n".join(line for line in lines if line).strip())


def extract_text(node: Element) -> str:
    """Extract text, inline equations, line boundaries, excluding ignored content."""
    def visit(item):
        if isinstance(item, str):
            return item
        if item.hidden or "data-gt-ignore" in item.attrs or item.tag in {"script", "style"}:
            return ""
        if item.attrs.get("data-gt-cat") == "equation_inline":
            return "$" + item.attrs.get("data-gt-latex", "") + "$"
        if item.tag == "br":
            return "\n"
        value = "".join(visit(c) for c in item.children)
        return "\n" + value + "\n" if item.tag in BOUNDARIES else value
    return normalize(visit(node))


def table_html(node: Element) -> str:
    """Canonical table HTML: only structural tags, text and cell spans remain."""
    def visit(item):
        if isinstance(item, str):
            return escape(re.sub(r"\s+", " ", unicodedata.normalize("NFC", item)))
        if item.hidden or "data-gt-ignore" in item.attrs or item.tag in {"script", "style"}:
            return ""
        content = "".join(visit(c) for c in item.children)
        if item.tag == "document":
            return content
        attrs = "".join(f' {k}="{escape(v)}"' for k, v in sorted(item.attrs.items()) if k in {"rowspan", "colspan"})
        return f"<{item.tag}{attrs}>" + ("" if item.tag in VOID else content + f"</{item.tag}>")
    return re.sub(r">\s+<", "><", visit(node)).strip()


def extract(node: Element) -> str:
    cat = node.attrs.get("data-gt-cat")
    if cat == "table" or node.tag == "table":
        return table_html(node)
    if cat == "equation_isolated":
        return node.attrs.get("data-gt-latex", "")
    return extract_text(node)
