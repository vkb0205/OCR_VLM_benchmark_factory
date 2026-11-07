"""Phase 1: draw first-page overlays and check every PNG's dimensions."""
from pathlib import Path
import json
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[2]
run = root / "OCR_VLM_benchmark_factory/out/uniqueness_phase0_attempt3"
pages = blocks = 0
for path in sorted(run.glob("**/extra/boxes.json")):
    data = json.loads(path.read_text(encoding="utf-8"))
    folder = path.parent.parent
    for page in data["pages"]:
        image = Image.open(folder / "images" / f"page_{page['index']:03}.png").convert("RGB")
        assert image.size == (page["image_width"], page["image_height"]), (path, page["index"], image.size)
        pages += 1
        blocks += len(page["blocks"])
        if page["index"] != 1: continue
        draw = ImageDraw.Draw(image)
        for box in page["blocks"]: draw.polygon(list(zip(box["poly"][::2], box["poly"][1::2])), outline="red", width=3)
        image.thumbnail((700, 1000))
        image.save(Path(__file__).parent / (folder.parents[2].name + "_overlay.png"))
print(f"PASS: {pages} pages, {blocks} blocks; 4 first-page overlays")
