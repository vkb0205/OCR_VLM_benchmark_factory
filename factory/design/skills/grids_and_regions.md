# Grids and regions

The code builds `title_page`, `body`, `references`, and `appendix` pages and places every required slot once. The design agent chooses each role's sheet size, region boxes, flow, and float defaults in `layout_plan`.

Each role has `size`, `body_font_size_pt`, `regions`, `flow`, and `float_defaults`. A region has a unique name, an ascending positive `chain`, and a box `{x,y,w,h}` in millimetres or percent of `<main>`. Keep boxes inside the main area and leave enough room for at least 35 average characters per line. The first region is named `body`. Flow slots and chains must match the role contract exactly and traverse every region in ascending chain order.

Use adjacent regions for columns. Do not use CSS `column-count`: content paginates down the region chains. Floats must fit their declared span and stay whole. A wide table can use `wide_table_page` with one landscape region and a `min_columns` threshold. The page frame, header, footer, page number, and `<main>` are code-owned; style them without repositioning or resizing them. Never move or resize `[data-region]` with CSS.
