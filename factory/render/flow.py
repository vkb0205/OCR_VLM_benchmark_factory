"""Academic region flow helpers used by fill's measured browser pass."""


SPLIT_TEXT_AT_REGION_BREAK = r"""(eligible) => {
  const allow = new Set(eligible);
  const touched = new Set();
  const regions = [...document.querySelectorAll('[data-region]')]
    .filter(region => region.dataset.region !== 'footnotes');
  const rectOf = (node, start, end) => {
    const range = document.createRange();
    range.setStart(node, start); range.setEnd(node, end);
    return range.getBoundingClientRect();
  };
  const isSpace = value => /\s/u.test(value);
  const columnIndex = (x, region, columnWidth, step) =>
    Math.max(0, Math.floor((x - region.left) / step));

  for (const region of regions) {
    const style = getComputedStyle(region);
    const count = Math.max(1, parseInt(style.columnCount, 10) || 1);
    const gap = parseFloat(style.columnGap) || 0;
    const regionRect = region.getBoundingClientRect();
    const columnWidth = (regionRect.width - gap * (count - 1)) / count;
    const step = columnWidth + gap;
    for (const paragraph of [...region.querySelectorAll('p[data-block]')]) {
      if (!allow.has(paragraph.dataset.block)) continue;
      const walker = document.createTreeWalker(paragraph, NodeFilter.SHOW_TEXT);
      const textNodes = [];
      while (walker.nextNode()) {
        const node = walker.currentNode;
        if (node.parentElement.closest('.factory-math,.factory-display-math,.factory-footnote-mark')) continue;
        textNodes.push(node);
      }
      let split = null;
      for (const node of textNodes) {
        const value = node.nodeValue;
        for (let i = 0; i < value.length && !split;) {
          if (!isSpace(value[i])) { i++; continue; }
          let end = i + 1;
          while (end < value.length && isSpace(value[end])) end++;
          if (i > 0 && end < value.length && !isSpace(value[i - 1]) && !isSpace(value[end])) {
            const before = rectOf(node, i - 1, i);
            const after = rectOf(node, end, end + 1);
            const crossesColumn = count > 1 &&
              columnIndex(after.left, regionRect, columnWidth, step) >
              columnIndex(before.left, regionRect, columnWidth, step);
            const crossesPage = before.bottom <= regionRect.bottom + .5 &&
              after.bottom > regionRect.bottom + .5;
            if (crossesColumn || crossesPage) split = {node, offset: end};
          }
          i = end;
        }
        if (split) break;
      }
      if (!split) continue;
      const leftRange = document.createRange();
      leftRange.selectNodeContents(paragraph);
      leftRange.setEnd(split.node, split.offset);
      const rightRange = document.createRange();
      rightRange.setStart(split.node, split.offset);
      rightRange.setEnd(paragraph, paragraph.childNodes.length);
      const first = paragraph.cloneNode(false), second = paragraph.cloneNode(false);
      first.append(leftRange.cloneContents());
      second.append(rightRange.cloneContents());
      second.classList.add('flow-continuation');
      paragraph.replaceWith(first, second);
      touched.add(first.dataset.block);
    }
  }
  const fragments = {};
  for (const id of touched) {
    fragments[id] = [...document.querySelectorAll(`[data-region]:not([data-region="footnotes"]) p[data-block="${CSS.escape(id)}"]`)]
      .map(node => node.innerHTML);
  }
  return fragments;
}"""


def apply_text_splits(section, fragments):
    """Replace source paragraphs with browser-measured word-boundary pieces."""
    if not fragments:
        return 0

    from copy import deepcopy
    from factory.contract.extract import Element
    from factory.render.fill import replace_inner

    replacements = 0
    for block_id, inner_html in fragments.items():
        if len(inner_html) < 2:
            continue
        matches = [node for node in section.walk()
                   if node.tag == 'p' and node.attrs.get('data-block') == block_id]
        if not matches:
            continue
        original = matches[0]
        parent = original.parent
        position = parent.children.index(original)
        pieces = []
        for index, markup in enumerate(inner_html):
            node = deepcopy(original)
            node.children = []
            replace_inner(node, markup)
            classes = node.attrs.get('class', '').split()
            if index:
                classes.append('flow-continuation')
            node.attrs['class'] = ' '.join(dict.fromkeys(classes))
            node.parent = parent
            pieces.append(node)
        for match in matches:
            match.parent = None
        parent.children[position:position + len(matches)] = pieces
        replacements += len(pieces) - len(matches)
    return replacements


def prepare_footnotes(section, built):
    """Move referenced notes into the page footnote region that has their mark."""
    from factory.contract.extract import Element, parse_html

    areas = [node for node in section.walk()
             if 'academic-footnotes' in node.attrs.get('class', '').split()]
    if not areas:
        return
    area = areas[0]
    managed = {bid for bid, block in built.blocks.items()
               if bid.startswith('fn_') and block.cat == 'footnote'}
    marks = [node for node in section.walk() if node.attrs.get('data-target-id')]
    targets = []
    for mark in marks:
        target = mark.attrs['data-target-id']
        if target in managed and target not in targets:
            targets.append(target)
    target_set = managed

    def remove_targets(node):
        kept = []
        for child in node.children:
            if isinstance(child, Element) and child.attrs.get('data-block') in target_set:
                child.parent = None
                continue
            if isinstance(child, Element):
                remove_targets(child)
            kept.append(child)
        node.children = kept

    remove_targets(section)
    area.children = []
    main = next((node for node in section.walk()
                 if node.attrs.get('data-region') == 'body'), None)
    if not main:
        return
    for target in targets:
        parsed = parse_html(built.inner[target])
        for child in parsed.children:
            if isinstance(child, Element):
                child.parent = area
            area.children.append(child)
    classes = main.attrs.get('class', '').split()
    if targets:
        if 'has-footnotes' not in classes:
            classes.append('has-footnotes')
        main.attrs['class'] = ' '.join(classes)
    else:
        main.attrs['class'] = ' '.join(x for x in classes if x != 'has-footnotes')
        reset_footnote_reserve(section)


def reset_footnote_reserve(section):
    """Restore the template's base region height after its notes move away."""
    import re

    for node in section.walk():
        if 'data-footnote-base' not in node.attrs:
            continue
        style = node.attrs.get('style', '')
        style = re.sub(r'(?:^|;)\s*height\s*:\s*[^;]+;?', '', style).strip(' ;')
        if style:
            node.attrs['style'] = style
        else:
            node.attrs.pop('style', None)
        node.attrs.pop('data-footnote-base', None)
        node.attrs.pop('data-footnote-reserved', None)


def queue_floats_after_first_reference(section, content, built):
    """Keep an inline float after the first body block that references it."""
    import re
    from factory.contract.extract import Element

    body = content.values.get('body', [])
    main = next((node for node in section.walk() if node.attrs.get('data-region') == 'body'), None)
    if main is None:
        return

    def block_id(item, index):
        source = item.get('id')
        return 'paper_' + source.replace(':', '_') if source else f"paper_{item['type']}_{index:02}"

    first_reference = {}
    floats = []
    for index, item in enumerate(body):
        kind = item.get('type')
        if kind in {'table', 'chart', 'figure'}:
            floats.append((index, item['id']))
        if kind in {'heading', 'paragraph'}:
            texts = [(item.get('text', ''), block_id(item, index + 1))]
        elif kind == 'list':
            base = block_id(item, index + 1)
            texts = [(value, f'{base}_item_{item_index}') for item_index, value in enumerate(item['items'], 1)]
        elif kind == 'box':
            texts = [(item.get('title', '') + ' ' + item.get('text', ''), block_id(item, index + 1))]
        else:
            texts = []
        for text, anchor_id in texts:
            for target in re.findall(r'\\ref\{([^}]+)\}', text):
                first_reference.setdefault(target, (index, anchor_id))

    direct = [node for node in main.children if isinstance(node, Element)]
    for index, float_id in reversed(floats):
        reference = first_reference.get(float_id)
        if reference is None or reference[0] <= index:
            continue
        anchor_id = reference[1]
        anchor = next((node for node in main.walk() if node.attrs.get('data-block') == anchor_id), None)
        if anchor is None:
            continue
        anchor_top = anchor
        while anchor_top.parent is not main and anchor_top.parent is not None:
            anchor_top = anchor_top.parent
        group = []
        for node in direct:
            bid = node.attrs.get('data-block')
            block = built.blocks.get(bid)
            if bid == 'paper_' + float_id.replace(':', '_') or (block and block.parent == 'paper_' + float_id.replace(':', '_')):
                group.append(node)
        if not group or anchor_top in group:
            continue
        for node in group:
            if node in main.children:
                main.children.remove(node)
        position = main.children.index(anchor_top) + 1
        main.children[position:position] = group
        for node in group:
            node.parent = main
            if node.attrs.get('data-block') == 'paper_' + float_id.replace(':', '_'):
                node.attrs['data-float-delayed'] = ''
        direct = [node for node in main.children if isinstance(node, Element)]
