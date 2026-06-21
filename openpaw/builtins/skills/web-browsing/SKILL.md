---
name: web-browsing
description: Browser automation workflow using accessibility tree snapshots, element interaction by numeric reference, JavaScript execution for custom components, and domain restrictions
inject: summary
---

# Web Browsing

## Workflow

Use `browser_snapshot` as your primary page understanding tool. It returns an
accessibility tree with numbered element references — use these numbers with
`browser_click`, `browser_type`, and `browser_select` to interact with elements.

Do NOT send screenshots unless the user explicitly asks. The accessibility tree
is your primary interface for understanding page content and structure.

### Standard Browser Flow

1. `browser_navigate(url)` — go to the page
2. `browser_snapshot()` — read the accessibility tree
3. `browser_click(ref)` / `browser_type(ref, text)` — interact with elements
4. `browser_snapshot()` — re-read after interaction to verify state
5. `browser_close()` — close when done

### Multi-Selection in Custom Dropdowns

Custom React/Vue dropdowns often re-render their DOM after each click, making
element references unstable. Two strategies handle this:

**Strategy 1: `keep_refs=True`** — For sequential clicks in the same dropdown:

```
browser_snapshot()           → get initial refs
browser_click(3, keep_refs=True)  → click first item, auto-refreshes refs
browser_click(5, keep_refs=True)  → click second item, auto-refreshes refs
browser_click(7, keep_refs=True)  → click third item, auto-refreshes refs
```

The `keep_refs` flag auto-refreshes the snapshot after each click so you get
updated refs without a separate `browser_snapshot` call.

**Strategy 2: `browser_execute_js`** — For batch operations, bypass the UI entirely:

```
browser_execute_js(
  script="document.querySelectorAll('.dropdown input[type=checkbox]').forEach(cb => { if (!cb.checked) cb.click(); })"
)
```

This directly manipulates the DOM in a single call — no ref invalidation,
no re-rendering between selections. Use this when:
- You need to select many items at once
- The dropdown re-renders unpredictably after each click
- You need to query the current selection state
- Standard `browser_select` fails ("not a <select> element")

### JavaScript Execution

`browser_execute_js(script, arg)` evaluates JavaScript in the page context.
Use it for:

- **Direct DOM manipulation**: Click elements by CSS selector, set values
- **State queries**: Read current checkbox states, input values, element counts
- **Event dispatch**: Trigger change/input events on custom components
- **Workarounds**: When accessibility tree interaction fails for custom UI

Examples:
```javascript
// Query element count
document.querySelectorAll('.search-result').length

// Read current checkbox states
JSON.stringify([...document.querySelectorAll('input[type=checkbox]')].map(e => ({name: e.name, checked: e.checked})))

// Click all unchecked items
([...document.querySelectorAll('.item')].filter(e => !e.classList.contains('selected')).forEach(e => e.click()))
```

### Domain Restrictions

Your browser may have domain allowlists or blocklists configured. If navigation
is blocked, inform the user about the restriction rather than retrying.

### Browser Lifecycle

Browser sessions persist until you close them or the conversation is reset
(via `/new` or `/compact`). Cookies may persist across agent runs if configured.

### Tips

- Always snapshot after navigation or interaction to verify the page state changed
- Use element reference numbers, not CSS selectors (for standard interactions)
- For multi-step workflows, snapshot between each step
- Use `keep_refs=True` when clicking multiple items in the same dropdown
- Use `browser_execute_js` when the accessibility tree is unreliable for custom components
- Downloaded files are saved to `workspace/downloads/`
- Screenshots are saved to `workspace/screenshots/`
