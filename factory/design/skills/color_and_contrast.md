# Color and contrast

Text and its actual rendered background must meet a contrast ratio of at least 4.5:1. Treat the design-spec palette as a concise description of paper/background, ink, and accent; the browser gate evaluates rendered text, including nested elements. Do not rely on a palette declaration to compensate for a failing rendered color.

Use color for hierarchy and navigation, with restrained accents appropriate to long-form print. Keep links, rules, shaded panels, and table headers distinct without making small text low contrast. Avoid large dark areas that consume ink unless the layout clearly benefits. Use CSS borders, backgrounds, and spacing for ornament; never create words or labels with `content:`.
