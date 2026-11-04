"""Offline Chromium rendering and geometry measurement."""

from contextlib import asynccontextmanager
import os
from pathlib import Path
import sys

from playwright.async_api import Error as PlaywrightError, TimeoutError as BrowserTimeout, async_playwright


class Browser:
    """One Chromium process with isolated, offline pages for each operation."""

    def __init__(self, timeout_ms: int = 15000):
        self.timeout_ms = timeout_ms
        self.recoveries = []

    async def __aenter__(self):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(Path(sys.prefix) / "ms-playwright")
        self.playwright = await async_playwright().start()
        try:
            # The macOS headless shell's GPU child can crash when run under
            # pytest. Keep the GPU service in the browser process on that platform.
            self.chromium = await self.playwright.chromium.launch(
                headless=True, args=["--in-process-gpu"] if sys.platform == "darwin" else [])
        except PlaywrightError as exc:
            await self.playwright.stop()
            raise RuntimeError("Chromium could not start. Install it with: "
                "PLAYWRIGHT_BROWSERS_PATH=.venv/ms-playwright .venv/bin/playwright install chromium\n"
                + str(exc)) from exc
        except BaseException:
            await self.playwright.stop()
            raise
        return self

    async def __aexit__(self, *exc):
        await self.chromium.close()
        await self.playwright.stop()

    @asynccontextmanager
    async def page(self, html_path: Path, *, device_scale_factor: float = 1):
        # A fresh offline context can occasionally stall in Chromium startup.
        # Retry startup once, never a caller's measurement or validation result.
        for attempt in range(2):
            scope = (self._page_once(html_path) if device_scale_factor == 1
                     else self._page_once(html_path, device_scale_factor=device_scale_factor))
            try:
                opened = await scope.__aenter__()
                break
            except BrowserTimeout as exc:
                if attempt: raise
                self.recoveries.append({'path': str(html_path), 'stage': 'startup', 'error': str(exc).splitlines()[0]})
        try:
            yield opened
        finally:
            await scope.__aexit__(None, None, None)

    @asynccontextmanager
    async def _page_once(self, html_path: Path, *, device_scale_factor: float = 1):
        context = await self.chromium.new_context(viewport={"width": 794, "height": 1123}, device_scale_factor=device_scale_factor,
                                                  service_workers="block")
        # Readiness is a harness concern; generated HTML can stay script-free.
        await context.add_init_script("window.__FACTORY_READY__ = true;")
        blocked, failed = [], []

        async def offline(route):
            url = route.request.url
            if url.startswith(("file:", "data:")):
                await route.continue_()
            else:
                blocked.append(url)
                await route.abort()

        await context.route("**/*", offline)
        page = await context.new_page()
        page.on("requestfailed", lambda request: failed.append(request.url))
        try:
            await page.goto(Path(html_path).resolve().as_uri(), wait_until="load", timeout=self.timeout_ms)
            await page.wait_for_function("window.__FACTORY_READY__ === true", timeout=self.timeout_ms)
            await page.evaluate("document.fonts.ready")
            await page.wait_for_function("Array.from(document.images).every(i => i.complete && i.naturalWidth > 0)",
                                         timeout=self.timeout_ms)
            # Landscape and non-A4 pages get a viewport of their own size.
            size = await page.evaluate("(() => { const r = document.body.getBoundingClientRect();"
                                       " return [Math.ceil(r.right), Math.ceil(r.bottom)]; })()")
            if size[0] > 794 or size[1] > 1123:
                await page.set_viewport_size({"width": max(size[0], 794), "height": max(size[1], 1123)})
            yield page, blocked, failed
        finally:
            await context.close()

    async def render(self, html_path: Path, *, dpi: int = 96) -> bytes:
        if dpi < 1:
            raise ValueError("dpi must be positive")
        for attempt in range(2):
            try:
                return await (self._render_once(html_path) if dpi == 96
                              else self._render_once(html_path, dpi=dpi))
            except BrowserTimeout as exc:
                if attempt: raise
                self.recoveries.append({'path': str(html_path), 'stage': 'screenshot', 'error': str(exc).splitlines()[0]})

    async def _render_once(self, html_path: Path, *, dpi: int = 96) -> bytes:
        async with self.page(html_path, device_scale_factor=dpi / 96) as (page, blocked, failed):
            if blocked or failed:
                raise ValueError(f"Offline resources failed: {blocked + failed}")
            bounds = await page.locator("body").bounding_box()
            data = await page.screenshot(clip=bounds, animations="disabled")
            from PIL import Image
            from io import BytesIO
            image=Image.open(BytesIO(data))
            expected=(round(bounds['width']*dpi/96),round(bounds['height']*dpi/96))
            if image.size != expected:
                image=image.resize(expected,Image.Resampling.LANCZOS)
                out=BytesIO();image.save(out,format='PNG');data=out.getvalue()
            return data

    async def measure(self, html_path: Path) -> dict:
        async with self.page(html_path) as (page, blocked, failed):
            result = await page.evaluate("""() => {
                const body = document.body, b = body.getBoundingClientRect();
                const rect = r => ({x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom,right:r.right});
                const blocks = {}, clipped = [], uncovered = [];
                const outside = r => r.x < b.x-.7 || r.y < b.y-.7 || r.right > b.right+.7 || r.bottom > b.bottom+.7;
                const visible = e => { const s=getComputedStyle(e); return s.display!=='none' && s.visibility!=='hidden' && e.getClientRects().length; };
                for (const e of document.querySelectorAll('[data-gt-id]')) {
                    const r = e.getBoundingClientRect();
                    blocks[e.dataset.gtId] = [rect(r)];
                    const clips = getComputedStyle(e).overflow !== 'visible';
                    if (outside(r) || (clips && (e.scrollWidth > e.clientWidth+1 || e.scrollHeight > e.clientHeight+1)))
                        clipped.push(e.dataset.gtId);
                    for (const cell of e.querySelectorAll('td,th'))
                        if (cell.scrollWidth > cell.clientWidth+1 || cell.scrollHeight > cell.clientHeight+1)
                            clipped.push(e.dataset.gtId);
                    const walker = document.createTreeWalker(e, NodeFilter.SHOW_TEXT);
                    while (walker.nextNode()) {
                        if (!walker.currentNode.textContent.trim()) continue;
                        if (!visible(walker.currentNode.parentElement)) continue;
                        const range = document.createRange(); range.selectNodeContents(walker.currentNode);
                        for (const r of range.getClientRects()) {
                            if (outside(r) || r.left < e.getBoundingClientRect().left-.7 || r.right > e.getBoundingClientRect().right+.7)
                                clipped.push(e.dataset.gtId);
                        }
                    }
                }
                const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
                while(walker.nextNode()) {
                    const n=walker.currentNode, e=n.parentElement;
                    if (n.textContent.trim() && !e.closest('script,style,[data-gt-cat],[data-gt-ignore]') && visible(e))
                        uncovered.push(n.textContent.slice(0,80));
                }
                for (const e of body.querySelectorAll('img,svg'))
                    if (visible(e) && !e.closest('[data-gt-cat],[data-gt-ignore]')) uncovered.push(e.tagName);
                const main=document.querySelector('main');
                const mainOverflow=main && getComputedStyle(main).overflow!=='visible' &&
                    (main.scrollWidth>main.clientWidth+3 || main.scrollHeight>main.clientHeight+3);
                return {blocks, clipped:[...new Set(clipped)], uncovered,
                    overflow:body.scrollWidth>body.clientWidth+1 || body.scrollHeight>body.clientHeight+1 || !!mainOverflow,
                    body:rect(b), rows:[...document.querySelectorAll('tbody tr')].map(e=>rect(e.getBoundingClientRect())),
                    main:document.querySelector('main') ? rect(document.querySelector('main').getBoundingClientRect()) : null,
                    font_errors:[...document.fonts].filter(f=>f.status==='error').map(f=>f.family)};
            }""")
            result.update(blocked=blocked, failed=failed)
            return result
