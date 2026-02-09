"""Accessibility tree transformation for LLM-optimized browser snapshots."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SnapshotTransformer:
    """Transforms Playwright accessibility tree into LLM-optimized format.

    Converts raw accessibility snapshots into a compact text format with
    numeric references for interactive elements. This enables agents to
    interact with page elements using simple integer refs like [1], [2], etc.

    Only interactive elements receive refs. Non-interactive elements with
    meaningful text (headings, labels, etc.) are included for context but
    without refs.
    """

    INTERACTIVE_ROLES = frozenset(
        {
            "button",
            "link",
            "textbox",
            "checkbox",
            "radio",
            "combobox",
            "menuitem",
            "tab",
            "switch",
            "slider",
            "searchbox",
            "spinbutton",
        }
    )

    SKIP_ROLES = frozenset(
        {
            "generic",  # <div> wrappers - no semantic meaning
            "none",  # Semantically meaningless
            "group",  # Generic container (from CDP's GenericContainer)
        }
    )

    def __init__(self, max_depth: int = 10):
        """Initialize transformer.

        Args:
            max_depth: Maximum tree traversal depth to prevent excessive output.
        """
        self.max_depth = max_depth

    def transform(
        self, accessibility_tree: dict[str, Any]
    ) -> tuple[str, dict[int, dict[str, Any]]]:
        """Transform accessibility tree to indexed format.

        Traverses the tree, assigns sequential integer refs to interactive
        elements, and produces a human-readable text representation with
        indentation for hierarchy.

        Args:
            accessibility_tree: Raw output from page.accessibility.snapshot().

        Returns:
            Tuple of (formatted_text, ref_map) where:
                - formatted_text: Multi-line string with indented elements
                - ref_map: Dict mapping ref numbers to original node dicts
        """
        if not accessibility_tree:
            logger.debug("Empty accessibility tree provided")
            return "", {}

        lines: list[str] = []
        ref_map: dict[int, dict[str, Any]] = {}
        ref_counter = [1]  # Use list for mutability in nested function

        self._traverse(accessibility_tree, 0, ref_counter, lines, ref_map)

        formatted_text = "\n".join(lines)
        logger.debug(
            f"Transformed tree: {len(lines)} lines, {len(ref_map)} interactive elements"
        )

        return formatted_text, ref_map

    def _traverse(
        self,
        node: dict[str, Any],
        depth: int,
        ref_counter: list[int],
        lines: list[str],
        ref_map: dict[int, dict[str, Any]],
    ) -> None:
        """Recursively traverse the accessibility tree.

        Args:
            node: Current tree node.
            depth: Current depth (for indentation).
            ref_counter: Mutable counter for sequential ref assignment.
            lines: Accumulator for output lines.
            ref_map: Accumulator for ref-to-node mapping.
        """
        if depth > self.max_depth:
            logger.debug(f"Max depth {self.max_depth} reached, stopping traversal")
            return

        role = node.get("role", "")
        name = node.get("name", "")

        # Skip nodes without role (but still traverse children)
        if not role:
            for child in node.get("children", []):
                self._traverse(child, depth, ref_counter, lines, ref_map)
            return

        # Skip noisy container roles UNLESS they have a meaningful name
        # (e.g., generic with name "Navigation" should be kept)
        if role in self.SKIP_ROLES and not name:
            for child in node.get("children", []):
                self._traverse(child, depth, ref_counter, lines, ref_map)
            return

        # Build element representation
        indent = "  " * depth
        is_interactive = role in self.INTERACTIVE_ROLES

        # Assign ref if interactive
        ref_str = ""
        if is_interactive:
            ref_num = ref_counter[0]
            ref_counter[0] += 1
            ref_str = f"[{ref_num}] "
            ref_map[ref_num] = node

        # Build element description
        parts = []
        if name:
            parts.append(name)

        # Add role annotation
        if role:
            role_parts = [role]

            # Add state annotations
            if node.get("checked") is not None:
                role_parts.append("checked" if node.get("checked") else "unchecked")

            if node.get("disabled"):
                role_parts.append("disabled")

            if node.get("level"):
                role_parts.append(f"level {node.get('level')}")

            if "value" in node and node.get("value"):
                # Show value for inputs
                role_parts.append(f'value: "{node.get("value")}"')

            parts.append(f"({', '.join(role_parts)})")

        element_desc = " ".join(parts)

        if element_desc:  # Only add line if there's something to show
            lines.append(f"{indent}{ref_str}{element_desc}")

        # Traverse children
        for child in node.get("children", []):
            self._traverse(child, depth + 1, ref_counter, lines, ref_map)
