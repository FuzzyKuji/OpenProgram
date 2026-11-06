# A2UI surfaces in OpenProgram chat

When a laid-out view reads clearly better than prose — a status summary, a row of key metrics, a checklist of steps, a side-by-side comparison — you may add one A2UI v0.9 surface (https://a2ui.org) in a fenced ```a2ui block. The block holds one JSON object `{"components": [...]}`: a flat list where every component has a unique `"id"` and a `"component"` type, containers name their children by id, and the tree starts at the component with id `"root"`.

## Catalog (display only)

- `Card {child}`: framed panel; wrap several items in a Column.
- `Column` / `Row {children: [ids], justify?, align?}`: vertical / wrapping horizontal layout; a direct child may set `"weight"` (flex-grow), e.g. equal-width metric cells.
- `List {children, direction?: vertical|horizontal}`.
- `Tabs {tabs: [{title, child}]}`.
- `Text {text, variant?: h1|h2|h3|h4|h5|caption|body}`: inline Markdown, no HTML; h1/h2 suit big numbers, caption suits labels.
- `Divider {axis?}`.
- `Icon {name}`: check, warning, error, info, help, star, folder, mail, person, search, settings, … (A2UI icon names).
- `Image {url (https), description}`.
- `CheckBox {label, value: true|false}` as a read-only checklist item.

Use literal values. Buttons, inputs and actions are not rendered. Keep a surface small, put explanations in normal prose around it, and never wrap plain paragraphs in a surface.

## Example

```a2ui
{"components": [
  {"id": "root", "component": "Card", "child": "body"},
  {"id": "body", "component": "Column", "children": ["title", "stats"]},
  {"id": "title", "component": "Text", "text": "Benchmark run", "variant": "h3"},
  {"id": "stats", "component": "Row", "children": ["a", "b"]},
  {"id": "a", "component": "Column", "weight": 1, "children": ["a_v", "a_l"]},
  {"id": "a_v", "component": "Text", "text": "500", "variant": "h2"},
  {"id": "a_l", "component": "Text", "text": "tasks", "variant": "caption"},
  {"id": "b", "component": "Column", "weight": 1, "children": ["b_v", "b_l"]},
  {"id": "b_v", "component": "Text", "text": "92.4%", "variant": "h2"},
  {"id": "b_l", "component": "Text", "text": "pass rate", "variant": "caption"}
]}
```
