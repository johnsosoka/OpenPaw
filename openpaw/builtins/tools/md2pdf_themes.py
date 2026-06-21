"""CSS themes for the md2pdf builtin.

Three production-ready themes for AI-generated markdown reports converted to PDF
via WeasyPrint. All themes use system font stacks (no web fonts), @page rules for
letter-size layout, and handle Pygments codehilite, tables, Mermaid diagrams, and
the AI-repaired diagram indicator.

Usage:
    from openpaw.builtins.tools.md2pdf_themes import THEMES, DEFAULT_THEME

    css = THEMES.get(theme_name, THEMES[DEFAULT_THEME])
"""

# ---------------------------------------------------------------------------
# THEME: minimal
# ---------------------------------------------------------------------------
# Clean academic-paper aesthetic. Generous whitespace, neutral grays, simple
# borders. Prioritizes readability over structure. The default theme.
# ---------------------------------------------------------------------------

THEME_MINIMAL = """
/* ============================================================
   MINIMAL THEME — Clean, academic, generous whitespace
   ============================================================ */

/* Page setup — Letter size, 1" margins */
@page {
    size: letter;
    margin: 1in;
}

/* Base document */
html, body {
    font-family: "Georgia", "Times New Roman", "DejaVu Serif", serif;
    font-size: 11pt;
    line-height: 1.7;
    color: #222222;
    background: #ffffff;
    margin: 0;
    padding: 0;
}

/* ── Headings ── */
h1, h2, h3, h4, h5, h6 {
    font-family: "Helvetica Neue", "Arial", "Liberation Sans", sans-serif;
    font-weight: 600;
    color: #1a1a1a;
    margin-top: 1.6em;
    margin-bottom: 0.4em;
    line-height: 1.25;
    page-break-after: avoid;
}

h1 {
    font-size: 22pt;
    font-weight: 700;
    border-bottom: 1.5pt solid #cccccc;
    padding-bottom: 0.25em;
    margin-top: 0;
}

h2 {
    font-size: 16pt;
    border-bottom: 0.75pt solid #dddddd;
    padding-bottom: 0.15em;
}

h3 {
    font-size: 13pt;
}

h4 {
    font-size: 11.5pt;
    font-style: italic;
    font-weight: 600;
}

/* ── Body text ── */
p {
    margin: 0 0 0.85em 0;
    orphans: 3;
    widows: 3;
}

/* ── Links — readable in print, no distracting underlines ── */
a {
    color: #444444;
    text-decoration: none;
}

a:after {
    content: "";
}

/* ── Horizontal rules ── */
hr {
    border: none;
    border-top: 0.75pt solid #dddddd;
    margin: 1.5em 0;
}

/* ── Lists ── */
ul, ol {
    margin: 0 0 0.85em 0;
    padding-left: 1.5em;
}

li {
    margin-bottom: 0.3em;
    line-height: 1.6;
}

li > ul,
li > ol {
    margin-top: 0.2em;
    margin-bottom: 0.2em;
}

/* ── Inline code ── */
code {
    font-family: "Courier New", "Courier", "DejaVu Sans Mono", monospace;
    font-size: 9.5pt;
    background: #f5f5f5;
    color: #333333;
    padding: 0.1em 0.35em;
    border-radius: 2pt;
    border: 0.5pt solid #e0e0e0;
}

/* ── Code blocks — Pygments codehilite wrapper ── */
div.codehilite {
    background: #f8f8f8;
    border: 0.75pt solid #e0e0e0;
    border-radius: 3pt;
    padding: 0.75em 1em;
    margin: 1em 0;
    page-break-inside: avoid;
    overflow: hidden;
}

div.codehilite pre {
    margin: 0;
    padding: 0;
    font-family: "Courier New", "Courier", "DejaVu Sans Mono", monospace;
    font-size: 8.5pt;
    line-height: 1.45;
    color: #333333;
    background: transparent;
    white-space: pre-wrap;
    overflow-wrap: break-word;
    word-break: break-all;
}

/* Override inline code style inside code blocks */
div.codehilite pre code {
    background: transparent;
    border: none;
    padding: 0;
    font-size: inherit;
    color: inherit;
}

/* Fenced code without codehilite (fallback) */
pre {
    background: #f8f8f8;
    border: 0.75pt solid #e0e0e0;
    border-radius: 3pt;
    padding: 0.75em 1em;
    margin: 1em 0;
    font-family: "Courier New", "Courier", "DejaVu Sans Mono", monospace;
    font-size: 8.5pt;
    line-height: 1.45;
    white-space: pre-wrap;
    overflow-wrap: break-word;
    word-break: break-all;
    page-break-inside: avoid;
}

pre code {
    background: transparent;
    border: none;
    padding: 0;
    font-size: inherit;
    color: inherit;
}

/* ── Tables ── */
table {
    border-collapse: collapse;
    width: 100%;
    margin: 1em 0;
    font-size: 10pt;
    page-break-inside: auto;
}

thead {
    background: #f0f0f0;
}

th {
    font-family: "Helvetica Neue", "Arial", "Liberation Sans", sans-serif;
    font-weight: 600;
    text-align: left;
    padding: 0.45em 0.75em;
    border: 0.75pt solid #cccccc;
    color: #1a1a1a;
}

td {
    padding: 0.4em 0.75em;
    border: 0.75pt solid #dddddd;
    vertical-align: top;
    line-height: 1.5;
}

/* Alternating row colors */
tbody tr:nth-child(even) {
    background: #fafafa;
}

tbody tr:nth-child(odd) {
    background: #ffffff;
}

/* ── Blockquotes ── */
blockquote {
    margin: 1em 0 1em 0;
    padding: 0.6em 1em;
    border-left: 3pt solid #cccccc;
    background: #f9f9f9;
    color: #555555;
    font-style: italic;
}

blockquote p {
    margin: 0 0 0.4em 0;
}

blockquote p:last-child {
    margin-bottom: 0;
}

/* ── Mermaid diagrams ── */
/* Mermaid renders as SVG inside a container div */
.mermaid,
div[class*="mermaid"],
p > img[src*="mermaid"],
svg[id*="mermaid"],
svg[class*="mermaid"] {
    display: block;
    text-align: center;
    margin: 1.25em auto;
    max-width: 100%;
    page-break-inside: avoid;
}

/* SVG inside mermaid wrapper */
.mermaid svg,
div[class*="mermaid"] svg {
    display: block;
    margin: 0 auto;
    max-width: 100%;
    height: auto;
}

/* ── AI-repaired diagram indicator ── */
.diagram-repaired {
    border: 1pt dashed #bbbbbb;
    background: #fefefe;
    padding: 0.25em;
    page-break-inside: avoid;
}

.diagram-repaired::before {
    content: "Note: diagram was automatically repaired";
    display: block;
    font-family: "Helvetica Neue", "Arial", "Liberation Sans", sans-serif;
    font-size: 8pt;
    color: #999999;
    font-style: italic;
    text-align: right;
    margin-bottom: 0.3em;
}

/* ── Table of Contents (from toc extension) ── */
div.toc {
    background: #f9f9f9;
    border: 0.75pt solid #e0e0e0;
    border-radius: 3pt;
    padding: 0.75em 1em;
    margin-bottom: 1.5em;
    font-size: 10pt;
}

div.toc ul {
    margin: 0;
    padding-left: 1.25em;
}

div.toc li {
    margin-bottom: 0.15em;
}

/* ── Print media overrides ── */
@media print {
    body {
        font-size: 11pt;
    }

    h1, h2, h3, h4 {
        page-break-after: avoid;
    }

    table, div.codehilite, pre, blockquote {
        page-break-inside: avoid;
    }

    tr {
        page-break-inside: avoid;
    }
}
"""


# ---------------------------------------------------------------------------
# THEME: professional
# ---------------------------------------------------------------------------
# Business report style. Dark table headers, indigo accent, stronger visual
# hierarchy. Designed for executive summaries and formal deliverables.
# ---------------------------------------------------------------------------

THEME_PROFESSIONAL = """
/* ============================================================
   PROFESSIONAL THEME — Business report, structured, polished
   ============================================================ */

/* Page setup — Letter size, 1" margins */
@page {
    size: letter;
    margin: 1in;
}

/* Base document */
html, body {
    font-family: "Helvetica Neue", "Arial", "Liberation Sans", sans-serif;
    font-size: 10.5pt;
    line-height: 1.6;
    color: #1c1c1c;
    background: #ffffff;
    margin: 0;
    padding: 0;
}

/* ── Headings ── */
h1, h2, h3, h4, h5, h6 {
    font-weight: 700;
    color: #1a1a2e;
    margin-top: 1.5em;
    margin-bottom: 0.45em;
    line-height: 1.2;
    page-break-after: avoid;
}

h1 {
    font-size: 24pt;
    color: #1a1a2e;
    border-bottom: 2pt solid #3730a3;
    padding-bottom: 0.3em;
    margin-top: 0;
    letter-spacing: -0.02em;
}

h2 {
    font-size: 15pt;
    color: #1a1a2e;
    border-bottom: 1pt solid #c7d2fe;
    padding-bottom: 0.2em;
    margin-top: 1.75em;
}

h3 {
    font-size: 12.5pt;
    color: #312e81;
}

h4 {
    font-size: 9.5pt;
    color: #4338ca;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}

/* ── Body text ── */
p {
    margin: 0 0 0.8em 0;
    orphans: 3;
    widows: 3;
}

/* ── Links ── */
a {
    color: #4338ca;
    text-decoration: none;
}

/* ── Horizontal rules ── */
hr {
    border: none;
    border-top: 1pt solid #c7d2fe;
    margin: 1.5em 0;
}

/* ── Lists ── */
ul, ol {
    margin: 0 0 0.8em 0;
    padding-left: 1.5em;
}

li {
    margin-bottom: 0.35em;
    line-height: 1.55;
}

li > ul,
li > ol {
    margin-top: 0.2em;
    margin-bottom: 0.2em;
}

/* ── Inline code ── */
code {
    font-family: "Courier New", "Courier", "DejaVu Sans Mono", monospace;
    font-size: 9pt;
    background: #eef2ff;
    color: #3730a3;
    padding: 0.1em 0.35em;
    border-radius: 2pt;
    border: 0.5pt solid #c7d2fe;
}

/* ── Code blocks — Pygments codehilite wrapper ── */
div.codehilite {
    background: #f8f9ff;
    border: 1pt solid #c7d2fe;
    border-left: 3pt solid #4338ca;
    border-radius: 2pt;
    padding: 0.7em 1em;
    margin: 1em 0;
    page-break-inside: avoid;
    overflow: hidden;
}

div.codehilite pre {
    margin: 0;
    padding: 0;
    font-family: "Courier New", "Courier", "DejaVu Sans Mono", monospace;
    font-size: 8.5pt;
    line-height: 1.45;
    color: #1e1b4b;
    background: transparent;
    white-space: pre-wrap;
    overflow-wrap: break-word;
    word-break: break-all;
}

div.codehilite pre code {
    background: transparent;
    border: none;
    padding: 0;
    font-size: inherit;
    color: inherit;
}

/* Fenced code fallback */
pre {
    background: #f8f9ff;
    border: 1pt solid #c7d2fe;
    border-left: 3pt solid #4338ca;
    border-radius: 2pt;
    padding: 0.7em 1em;
    margin: 1em 0;
    font-family: "Courier New", "Courier", "DejaVu Sans Mono", monospace;
    font-size: 8.5pt;
    line-height: 1.45;
    white-space: pre-wrap;
    overflow-wrap: break-word;
    word-break: break-all;
    page-break-inside: avoid;
}

pre code {
    background: transparent;
    border: none;
    padding: 0;
    font-size: inherit;
    color: inherit;
}

/* ── Tables ── */
table {
    border-collapse: collapse;
    width: 100%;
    margin: 1em 0;
    font-size: 10pt;
    page-break-inside: auto;
}

thead {
    background: #1a1a2e;
    color: #ffffff;
}

th {
    font-weight: 600;
    text-align: left;
    padding: 0.5em 0.85em;
    border: 1pt solid #1a1a2e;
    color: #ffffff;
    font-size: 9.5pt;
    letter-spacing: 0.02em;
}

td {
    padding: 0.4em 0.85em;
    border: 0.75pt solid #c7d2fe;
    vertical-align: top;
    line-height: 1.5;
}

/* Alternating row colors */
tbody tr:nth-child(even) {
    background: #eef2ff;
}

tbody tr:nth-child(odd) {
    background: #ffffff;
}

/* ── Blockquotes ── */
blockquote {
    margin: 1em 0;
    padding: 0.6em 1em 0.6em 1.1em;
    border-left: 3.5pt solid #4338ca;
    background: #eef2ff;
    color: #312e81;
    font-style: normal;
}

blockquote p {
    margin: 0 0 0.4em 0;
}

blockquote p:last-child {
    margin-bottom: 0;
}

/* ── Mermaid diagrams ── */
.mermaid,
div[class*="mermaid"],
p > img[src*="mermaid"],
svg[id*="mermaid"],
svg[class*="mermaid"] {
    display: block;
    text-align: center;
    margin: 1.25em auto;
    max-width: 100%;
    page-break-inside: avoid;
}

.mermaid svg,
div[class*="mermaid"] svg {
    display: block;
    margin: 0 auto;
    max-width: 100%;
    height: auto;
}

/* ── AI-repaired diagram indicator ── */
.diagram-repaired {
    border: 1pt dashed #a5b4fc;
    background: #f5f7ff;
    padding: 0.25em;
    page-break-inside: avoid;
}

.diagram-repaired::before {
    content: "Note: diagram was automatically repaired";
    display: block;
    font-size: 7.5pt;
    color: #6366f1;
    font-style: italic;
    text-align: right;
    margin-bottom: 0.3em;
    font-family: "Helvetica Neue", "Arial", "Liberation Sans", sans-serif;
}

/* ── Table of Contents ── */
div.toc {
    background: #eef2ff;
    border: 1pt solid #c7d2fe;
    border-radius: 2pt;
    padding: 0.75em 1em;
    margin-bottom: 1.75em;
    font-size: 10pt;
}

div.toc ul {
    margin: 0;
    padding-left: 1.25em;
}

div.toc li {
    margin-bottom: 0.15em;
}

/* ── Print media overrides ── */
@media print {
    body {
        font-size: 10.5pt;
    }

    h1, h2, h3, h4 {
        page-break-after: avoid;
    }

    table, div.codehilite, pre, blockquote {
        page-break-inside: avoid;
    }

    tr {
        page-break-inside: avoid;
    }
}
"""


# ---------------------------------------------------------------------------
# THEME: technical
# ---------------------------------------------------------------------------
# Optimized for code-heavy and diagram-heavy reports. Dark code blocks (IDE
# style), tight spacing to fit more content, monospace-friendly layout.
# Designed for architecture docs, system reports, and technical references.
# ---------------------------------------------------------------------------

THEME_TECHNICAL = """
/* ============================================================
   TECHNICAL THEME — Code-dense, IDE-style code blocks, tight
   ============================================================ */

/* Page setup — Letter size, 1" margins */
@page {
    size: letter;
    margin: 1in;
}

/* Base document */
html, body {
    font-family: "Helvetica Neue", "Arial", "Liberation Sans", sans-serif;
    font-size: 10pt;
    line-height: 1.5;
    color: #1e1e1e;
    background: #ffffff;
    margin: 0;
    padding: 0;
}

/* ── Headings ── */
h1, h2, h3, h4, h5, h6 {
    font-weight: 700;
    color: #0f172a;
    margin-top: 1.35em;
    margin-bottom: 0.35em;
    line-height: 1.2;
    page-break-after: avoid;
}

h1 {
    font-size: 20pt;
    font-weight: 700;
    border-bottom: 2pt solid #334155;
    padding-bottom: 0.2em;
    margin-top: 0;
    color: #0f172a;
}

h2 {
    font-size: 14pt;
    border-bottom: 0.75pt solid #94a3b8;
    padding-bottom: 0.15em;
    color: #1e293b;
}

h3 {
    font-size: 11.5pt;
    color: #334155;
}

h4 {
    font-size: 8.5pt;
    font-weight: 700;
    color: #475569;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

/* ── Body text ── */
p {
    margin: 0 0 0.65em 0;
    orphans: 3;
    widows: 3;
}

/* ── Links ── */
a {
    color: #334155;
    text-decoration: none;
}

/* ── Horizontal rules ── */
hr {
    border: none;
    border-top: 1pt solid #e2e8f0;
    margin: 1em 0;
}

/* ── Lists — tighter spacing for dense content ── */
ul, ol {
    margin: 0 0 0.65em 0;
    padding-left: 1.35em;
}

li {
    margin-bottom: 0.2em;
    line-height: 1.45;
}

li > ul,
li > ol {
    margin-top: 0.15em;
    margin-bottom: 0.15em;
}

/* ── Inline code ── */
code {
    font-family: "Courier New", "Courier", "DejaVu Sans Mono", monospace;
    font-size: 9pt;
    background: #1e293b;
    color: #e2e8f0;
    padding: 0.1em 0.35em;
    border-radius: 2pt;
}

/* ── Code blocks — dark IDE-style, Pygments codehilite wrapper ── */
div.codehilite {
    background: #0f172a;
    border: 1pt solid #334155;
    border-radius: 3pt;
    padding: 0.8em 1.1em;
    margin: 0.75em 0;
    page-break-inside: avoid;
    overflow: hidden;
}

div.codehilite pre {
    margin: 0;
    padding: 0;
    font-family: "Courier New", "Courier", "DejaVu Sans Mono", monospace;
    font-size: 8pt;
    line-height: 1.4;
    color: #e2e8f0;
    background: transparent;
    white-space: pre-wrap;
    overflow-wrap: break-word;
    word-break: break-all;
}

div.codehilite pre code {
    background: transparent;
    border: none;
    padding: 0;
    font-size: inherit;
    color: inherit;
}

/* Pygments token colors for dark background — legible subset */
/* These are safe across common Pygments styles on dark bg */
div.codehilite .k,  /* Keyword */
div.codehilite .kd,
div.codehilite .kn,
div.codehilite .kr {
    color: #93c5fd;
}

div.codehilite .s,  /* String */
div.codehilite .s1,
div.codehilite .s2,
div.codehilite .sb {
    color: #86efac;
}

div.codehilite .c,  /* Comment */
div.codehilite .c1,
div.codehilite .cm {
    color: #64748b;
    font-style: italic;
}

div.codehilite .n,  /* Name */
div.codehilite .na,
div.codehilite .nb {
    color: #e2e8f0;
}

div.codehilite .nf,  /* Function name */
div.codehilite .nc  /* Class name */ {
    color: #fbbf24;
}

div.codehilite .mi,  /* Integer literal */
div.codehilite .mf,  /* Float literal */
div.codehilite .m {
    color: #f9a8d4;
}

div.codehilite .o,  /* Operator */
div.codehilite .p {  /* Punctuation */
    color: #94a3b8;
}

/* Fenced code fallback — also dark */
pre {
    background: #0f172a;
    border: 1pt solid #334155;
    border-radius: 3pt;
    padding: 0.8em 1.1em;
    margin: 0.75em 0;
    font-family: "Courier New", "Courier", "DejaVu Sans Mono", monospace;
    font-size: 8pt;
    line-height: 1.4;
    color: #e2e8f0;
    white-space: pre-wrap;
    overflow-wrap: break-word;
    word-break: break-all;
    page-break-inside: avoid;
}

pre code {
    background: transparent;
    border: none;
    padding: 0;
    font-size: inherit;
    color: inherit;
}

/* ── Tables — compact, data-dense ── */
table {
    border-collapse: collapse;
    width: 100%;
    margin: 0.75em 0;
    font-size: 9.5pt;
    font-family: "Courier New", "Courier", "DejaVu Sans Mono", monospace;
    page-break-inside: auto;
}

thead {
    background: #1e293b;
    color: #e2e8f0;
}

th {
    font-family: "Helvetica Neue", "Arial", "Liberation Sans", sans-serif;
    font-weight: 700;
    text-align: left;
    padding: 0.4em 0.7em;
    border: 0.75pt solid #334155;
    color: #e2e8f0;
    font-size: 9pt;
    letter-spacing: 0.02em;
}

td {
    padding: 0.3em 0.7em;
    border: 0.75pt solid #cbd5e1;
    vertical-align: top;
    line-height: 1.4;
}

/* Alternating rows — subtle slate tones */
tbody tr:nth-child(even) {
    background: #f1f5f9;
}

tbody tr:nth-child(odd) {
    background: #ffffff;
}

/* ── Blockquotes — used for callouts/notes in technical docs ── */
blockquote {
    margin: 0.75em 0;
    padding: 0.5em 0.9em;
    border-left: 3pt solid #475569;
    background: #f8fafc;
    color: #475569;
    font-style: normal;
    font-size: 9.5pt;
}

blockquote p {
    margin: 0 0 0.3em 0;
    font-family: "Courier New", "Courier", "DejaVu Sans Mono", monospace;
}

blockquote p:last-child {
    margin-bottom: 0;
}

/* ── Mermaid diagrams ── */
.mermaid,
div[class*="mermaid"],
p > img[src*="mermaid"],
svg[id*="mermaid"],
svg[class*="mermaid"] {
    display: block;
    text-align: center;
    margin: 1em auto;
    max-width: 100%;
    page-break-inside: avoid;
    border: 0.75pt solid #e2e8f0;
    padding: 0.5em;
    background: #f8fafc;
}

.mermaid svg,
div[class*="mermaid"] svg {
    display: block;
    margin: 0 auto;
    max-width: 100%;
    height: auto;
}

/* ── AI-repaired diagram indicator ── */
.diagram-repaired {
    border: 1pt dashed #94a3b8;
    background: #f1f5f9;
    padding: 0.25em;
    page-break-inside: avoid;
}

.diagram-repaired::before {
    content: "Note: diagram was automatically repaired";
    display: block;
    font-family: "Courier New", "Courier", "DejaVu Sans Mono", monospace;
    font-size: 7.5pt;
    color: #64748b;
    font-style: italic;
    text-align: right;
    margin-bottom: 0.3em;
}

/* ── Table of Contents — monospace compact ── */
div.toc {
    background: #f8fafc;
    border: 0.75pt solid #e2e8f0;
    border-left: 2.5pt solid #334155;
    border-radius: 2pt;
    padding: 0.6em 0.9em;
    margin-bottom: 1.25em;
    font-size: 9.5pt;
    font-family: "Courier New", "Courier", "DejaVu Sans Mono", monospace;
}

div.toc ul {
    margin: 0;
    padding-left: 1.1em;
}

div.toc li {
    margin-bottom: 0.1em;
}

/* ── Print media overrides ── */
@media print {
    body {
        font-size: 10pt;
    }

    h1, h2, h3, h4 {
        page-break-after: avoid;
    }

    table, div.codehilite, pre, blockquote {
        page-break-inside: avoid;
    }

    tr {
        page-break-inside: avoid;
    }
}
"""


THEMES: dict[str, str] = {
    "minimal": THEME_MINIMAL,
    "professional": THEME_PROFESSIONAL,
    "technical": THEME_TECHNICAL,
}

DEFAULT_THEME = "minimal"
