"""Browser state: accessibility snapshots, tab listing, and page info."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class BrowserState:
    """Manages browser state queries and accessibility snapshots.

    Includes taking semantic snapshots of the page, listing open tabs,
    and extracting the accessibility tree via CDP.
    """

    def __init__(self, session: Any) -> None:
        """Initialize with parent BrowserSession.

        Args:
            session: The BrowserSession instance that owns this state.
        """
        self._session: Any = session

    def _check_active(self) -> str | None:
        """Return error message if browser is not active, else None."""
        if not self._session.is_active:
            return "Browser not active. Use browser_navigate first."
        return None

    async def snapshot(self) -> str:
        """Take accessibility snapshot with numbered element refs.

        Returns:
            Formatted snapshot text with [ref] annotations.
        """
        if error := self._check_active():
            return error

        try:
            # Get accessibility snapshot via CDP
            a11y_tree = await self._get_accessibility_tree()

            if not a11y_tree:
                return "Page snapshot empty (no accessible content)"

            # Transform to indexed format
            formatted_text, ref_map = self._session.snapshot_transformer.transform(a11y_tree)

            # Store ref map for element interaction
            self._session._ref_map = ref_map

            # Add header with metadata
            title = await self._session._page.title()
            url = self._session._page.url
            header = f"Page: {title}\nURL: {url}\nInteractive elements: {len(ref_map)}\n\n"

            logger.info(f"Snapshot captured: {len(ref_map)} interactive elements")
            return str(header) + str(formatted_text)

        except Exception as e:
            logger.error(f"Snapshot failed: {e}")
            return f"Snapshot failed: {str(e)}"

    async def get_tabs(self) -> str:
        """List all open tabs.

        Returns:
            Formatted list of tabs with indices.
        """
        if error := self._check_active():
            return error

        try:
            pages = self._session._context.pages
            lines: list[str] = ["Open tabs:"]

            for i, page in enumerate(pages):
                title = await page.title()
                url = page.url
                active = " (active)" if page == self._session._page else ""
                lines.append(f"  [{i}] {title} - {url}{active}")

            logger.info(f"Listed {len(pages)} tabs")
            return "\n".join(lines)

        except Exception as e:
            logger.error(f"List tabs failed: {e}")
            return f"List tabs failed: {str(e)}"

    async def _get_accessibility_tree(self) -> dict[str, Any] | None:
        """Get accessibility tree via CDP (Chrome DevTools Protocol).

        Playwright 1.58+ removed page.accessibility.snapshot(), so we use
        CDP's Accessibility.getFullAXTree instead and reconstruct the tree.

        Returns:
            Dict tree compatible with SnapshotTransformer, or None on error.
        """
        try:
            # Create CDP session
            try:
                client = await self._session._page.context.new_cdp_session(self._session._page)
            except Exception as e:
                logger.warning(f"Failed to create CDP session: {e}")
                return None

            try:
                # Get full accessibility tree from CDP
                response = await client.send("Accessibility.getFullAXTree")
                nodes: list[dict[str, Any]] = response.get("nodes", [])

                if not nodes:
                    logger.debug("CDP returned empty accessibility tree")
                    return None

                # Build node lookup by ID
                node_map: dict[str, dict[str, Any]] = {node["nodeId"]: node for node in nodes}

                # Helper to extract role string from CDP role object
                def get_role(node: dict[str, Any]) -> str | None:
                    role_obj = node.get("role", {})
                    value = role_obj.get("value", "") if isinstance(role_obj, dict) else ""

                    # Normalize role names (CDP uses internal names like "RootWebArea")
                    role_map: dict[str, str | None] = {
                        "RootWebArea": "WebArea",
                        "WebArea": "WebArea",
                        "GenericContainer": "group",
                        "StaticText": None,  # Skip - leaf noise
                        "InlineTextBox": None,  # Skip - leaf noise
                    }

                    # Use mapping if available, otherwise keep lowercase
                    if value in role_map:
                        return role_map[value]
                    return value.lower() if value else ""

                # Helper to extract name from CDP name object
                def get_name(node: dict[str, Any]) -> str:
                    name_obj = node.get("name", {})
                    return name_obj.get("value", "") if isinstance(name_obj, dict) else ""

                # Helper to extract properties dict
                def get_properties(node: dict[str, Any]) -> dict[str, Any]:
                    props: dict[str, Any] = {}
                    for prop in node.get("properties", []):
                        prop_name = prop.get("name", "")
                        prop_value = prop.get("value", {})

                        # Extract actual value based on type
                        if isinstance(prop_value, dict):
                            if "value" in prop_value:
                                props[prop_name] = prop_value["value"]
                        else:
                            props[prop_name] = prop_value

                    return props

                # Recursive function to build tree
                def build_tree(node_id: str) -> dict[str, Any] | None:
                    if node_id not in node_map:
                        return None

                    cdp_node = node_map[node_id]

                    # Skip ignored nodes (but include their children)
                    if cdp_node.get("ignored", False):
                        # Flatten through ignored nodes
                        children: list[dict[str, Any]] = []
                        for child_id in cdp_node.get("childIds", []):
                            child = build_tree(child_id)
                            if child:
                                children.append(child)
                        # Return children directly (unwrapped)
                        if len(children) == 1:
                            return children[0]
                        elif children:
                            return {"children": children}
                        return None

                    # Get role and skip internal leaf nodes
                    role = get_role(cdp_node)
                    if role is None:  # Explicitly filtered out (StaticText, etc.)
                        return None

                    # Build node dict
                    tree_node: dict[str, Any] = {}

                    if role:
                        tree_node["role"] = role

                    name = get_name(cdp_node)
                    if name:
                        tree_node["name"] = name

                    # Extract properties
                    props = get_properties(cdp_node)
                    if "level" in props:
                        tree_node["level"] = props["level"]
                    if "checked" in props:
                        tree_node["checked"] = props["checked"]
                    if "disabled" in props:
                        tree_node["disabled"] = props["disabled"]
                    if "value" in props and props["value"]:
                        tree_node["value"] = props["value"]

                    # Recursively build children
                    children = []
                    for child_id in cdp_node.get("childIds", []):
                        child = build_tree(child_id)
                        if child:
                            # Handle flattened children from ignored nodes
                            if isinstance(child, list):
                                children.extend(child)
                            elif isinstance(child, dict) and "children" in child and "role" not in child:
                                # Unwrap container with only children
                                children.extend(child["children"])
                            else:
                                children.append(child)

                    if children:
                        tree_node["children"] = children

                    return tree_node

                # Find root node (usually first node)
                root_id: str | None = nodes[0]["nodeId"] if nodes else None
                if not root_id:
                    return None

                tree = build_tree(root_id)
                return tree

            finally:
                # Clean up CDP session
                await client.detach()

        except Exception as e:
            logger.error(f"CDP accessibility tree extraction failed: {e}")
            return None
