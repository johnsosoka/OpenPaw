---
name: web-browsing
description: Browser automation workflow using accessibility tree snapshots, element interaction by numeric reference, and domain restrictions
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

### Domain Restrictions

Your browser may have domain allowlists or blocklists configured. If navigation
is blocked, inform the user about the restriction rather than retrying.

### Browser Lifecycle

Browser sessions persist until you close them or the conversation is reset
(via `/new` or `/compact`). Cookies may persist across agent runs if configured.

### Tips

- Always snapshot after navigation or interaction to verify the page state changed
- Use element reference numbers, not CSS selectors
- For multi-step workflows, snapshot between each step
- Downloaded files are saved to `workspace/downloads/`
- Screenshots are saved to `workspace/screenshots/`
