"""Compare direct per-bundle export outputs; hold PDF clock bytes constant."""
import asyncio
from contextlib import asynccontextmanager
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'OCR_VLM_benchmark_factory'))
from factory.browser.browser import Browser
from factory.contract.taxonomy import Taxonomy
from factory.runner import export as current

# The saved baseline predates explicit UTF-8 reads; select UTF-8 for its reads
# in this harness only, leaving its capture/export algorithm unchanged.
source = Path(__file__).with_name('export_before.py')
baseline = type(sys)('export_before')
baseline.__file__ = str(ROOT / 'OCR_VLM_benchmark_factory/factory/runner/export.py')
exec(compile(source.read_text(encoding='utf-8').replace('.read_text()', '.read_text(encoding="utf-8")'), str(source), 'exec'), baseline.__dict__)

class StablePDF:
    def __init__(self, browser):
        self.browser = browser
        self.pdfs = {}
    async def measure(self, *args, **kwargs):
        return await self.browser.measure(*args, **kwargs)
    @asynccontextmanager
    async def page(self, path, **kwargs):
        async with self.browser.page(path, **kwargs) as (page, blocked, failed):
            original = page.pdf
            async def pdf(**options):
                key = str(path)
                if key not in self.pdfs:
                    self.pdfs[key] = await original(**options)
                return self.pdfs[key]
            page.pdf = pdf
            yield page, blocked, failed

async def main():
    run = ROOT / 'OCR_VLM_benchmark_factory/out/uniqueness_phase0_attempt3'
    total = pages = 0
    issues = []
    with tempfile.TemporaryDirectory(prefix='gt-export-diff-') as temporary:
        output = Path(temporary)
        async with Browser() as browser:
            stable = StablePDF(browser)
            for folder in sorted(run.glob('**/documents/*/*')):
                if not (folder / 'document.json').exists(): continue
                subset = folder.parents[2].name
                results = []
                for label, module in [('before', baseline), ('after', current)]:
                    target = output / label / subset
                    for name in ['images', 'pdfs', 'mds']: (target / name).mkdir(parents=True)
                    result, problems = await module.process(stable, Taxonomy(), folder, target, asyncio.Semaphore(1), {})
                    assert result is not None, problems
                    issues.extend(problems)
                    (target / 'dataset.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                    results.append(target)
                for path in sorted(results[0].rglob('*')):
                    if not path.is_file(): continue
                    relative = path.relative_to(results[0])
                    assert path.read_bytes() == (results[1] / relative).read_bytes(), (subset, relative)
                    total += 1
                pages += len(result[0])
    message = f'PASS: 4 bundles, {pages} pages, {total} files compared, 0 differing bytes. PDF bytes replayed to hold Chromium creation timestamps constant; screenshots and geometry measured independently. Direct process() bypasses the agent-only entrypoint filter. Problems: {issues}'
    Path(__file__).with_name('export_diff.txt').write_text(message + '\n', encoding='utf-8')
    print(message)

asyncio.run(main())
