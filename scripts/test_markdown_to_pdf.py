"""End-to-end validation of markdown_to_pdf tool with PNG mermaid rendering."""
import importlib
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

logging.basicConfig(level=logging.WARNING)

tmpdir = tempfile.mkdtemp(prefix="md2pdf_test_")
os.environ["OPENPAW_WORKSPACE_PATH"] = tmpdir

test_md = Path(tmpdir) / "test_report.md"
test_md.write_text("""\
# OpenPaw Architecture Report

This report demonstrates mermaid diagram embedding in PDF output.

## System Architecture

```mermaid
graph TD
    A[User] --> B[Channel]
    B --> C[Queue]
    C --> D[Agent]
    D --> E[Tools]
```

## Message Flow

The following sequence diagram shows a typical message exchange:

```mermaid
sequenceDiagram
    participant U as User
    participant C as Channel
    participant Q as Queue
    participant A as Agent
    U->>C: Send message
    C->>Q: Enqueue
    Q->>A: Dequeue
    A->>U: Response
```

## Summary

Both diagrams above should render as visible images with text labels and colors.
""")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent_workspaces" / "krieger" / "tools"))

import markdown_to_pdf as m2p
importlib.reload(m2p)

m2p._WORKSPACE_ROOT = Path(tmpdir).resolve()
m2p._TOOL_DIR = Path(__file__).resolve().parent.parent / "agent_workspaces" / "krieger" / "tools"
m2p._STYLES_CSS = m2p._TOOL_DIR / "pdf_styles.css"

print(f"Workspace: {tmpdir}")
print("Running markdown_to_pdf...")

result = m2p.markdown_to_pdf.invoke({"markdown_path": "test_report.md"})
result_data = json.loads(result)

if "error" in result_data:
    print(f"FAILED: {result_data['error']}")
    sys.exit(1)

output_path = Path(tmpdir) / result_data["output_path"]
print(f"PDF: {output_path}")
print(f"Size: {result_data['size_kb']} KB")

# Copy to scripts/ for easy inspection
dest = Path(__file__).resolve().parent / "test_report_final.pdf"
import shutil
shutil.copy2(output_path, dest)
print(f"\nCopied to: {dest}")
print(f"open {dest}")
