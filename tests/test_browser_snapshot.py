"""Tests for browser accessibility tree snapshot transformer."""

import pytest

from openpaw.builtins.tools.browser.snapshot import SnapshotTransformer


class TestBasicTransformation:
    """Test basic snapshot transformation."""

    def test_empty_tree(self):
        """Empty tree should return empty string and map."""
        transformer = SnapshotTransformer()
        text, ref_map = transformer.transform({})
        assert text == ""
        assert ref_map == {}

    def test_single_button(self):
        """Single button should get ref [1]."""
        tree = {"role": "button", "name": "Click me"}
        transformer = SnapshotTransformer()
        text, ref_map = transformer.transform(tree)

        assert text == "[1] Click me (button)"
        assert 1 in ref_map
        assert ref_map[1] == tree

    def test_single_heading_no_ref(self):
        """Non-interactive heading should not get ref."""
        tree = {"role": "heading", "name": "Welcome", "level": 1}
        transformer = SnapshotTransformer()
        text, ref_map = transformer.transform(tree)

        assert text == "Welcome (heading, level 1)"
        assert ref_map == {}  # No refs for non-interactive

    def test_mixed_elements(self):
        """Mix of interactive and non-interactive elements."""
        tree = {
            "role": "WebArea",
            "name": "Test Page",
            "children": [
                {"role": "heading", "name": "Welcome", "level": 1},
                {"role": "button", "name": "Sign In"},
                {"role": "paragraph", "name": "Some text"},
                {"role": "link", "name": "Learn more"},
            ],
        }
        transformer = SnapshotTransformer()
        text, ref_map = transformer.transform(tree)

        lines = text.split("\n")
        assert "Test Page (WebArea)" in lines[0]
        assert "Welcome (heading, level 1)" in lines[1]
        assert "[1] Sign In (button)" in lines[2]
        assert "Some text (paragraph)" in lines[3]
        assert "[2] Learn more (link)" in lines[4]

        assert len(ref_map) == 2
        assert ref_map[1]["name"] == "Sign In"
        assert ref_map[2]["name"] == "Learn more"


class TestRefAssignment:
    """Test ref number assignment."""

    def test_sequential_refs(self):
        """Refs should be assigned sequentially."""
        tree = {
            "role": "WebArea",
            "children": [
                {"role": "button", "name": "First"},
                {"role": "link", "name": "Second"},
                {"role": "textbox", "name": "Third"},
                {"role": "checkbox", "name": "Fourth"},
            ],
        }
        transformer = SnapshotTransformer()
        text, ref_map = transformer.transform(tree)

        assert "[1] First (button)" in text
        assert "[2] Second (link)" in text
        assert "[3] Third (textbox)" in text
        assert "[4] Fourth (checkbox)" in text

        assert len(ref_map) == 4

    def test_only_interactive_get_refs(self):
        """Only interactive roles should receive refs."""
        tree = {
            "role": "WebArea",
            "children": [
                {"role": "heading", "name": "Title"},
                {"role": "button", "name": "Action"},
                {"role": "paragraph", "name": "Text"},
                {"role": "link", "name": "Nav"},
                {"role": "image", "name": "Logo"},
            ],
        }
        transformer = SnapshotTransformer()
        text, ref_map = transformer.transform(tree)

        # Only button and link should have refs
        assert "[1] Action (button)" in text
        assert "[2] Nav (link)" in text
        assert "Title (heading)" in text
        assert "Text (paragraph)" in text
        assert "Logo (image)" in text

        assert len(ref_map) == 2


class TestInteractiveRoles:
    """Test all interactive role types."""

    def test_all_interactive_roles_get_refs(self):
        """All defined interactive roles should receive refs."""
        interactive_roles = [
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
        ]

        children = [
            {"role": role, "name": f"Element {i}"}
            for i, role in enumerate(interactive_roles)
        ]
        tree = {"role": "WebArea", "children": children}

        transformer = SnapshotTransformer()
        text, ref_map = transformer.transform(tree)

        # All should have refs
        for i in range(1, len(interactive_roles) + 1):
            assert f"[{i}]" in text

        assert len(ref_map) == len(interactive_roles)


class TestHierarchy:
    """Test hierarchical structure and indentation."""

    def test_nested_elements(self):
        """Nested elements should be indented."""
        tree = {
            "role": "WebArea",
            "name": "Page",
            "children": [
                {
                    "role": "group",
                    "name": "Form",
                    "children": [
                        {"role": "textbox", "name": "Username"},
                        {"role": "textbox", "name": "Password"},
                        {"role": "button", "name": "Submit"},
                    ],
                }
            ],
        }
        transformer = SnapshotTransformer()
        text, ref_map = transformer.transform(tree)

        lines = text.split("\n")
        # Page at depth 0 (no indent)
        assert lines[0] == "Page (WebArea)"
        # Form at depth 1 (2 spaces)
        assert lines[1] == "  Form (group)"
        # Form children at depth 2 (4 spaces)
        assert lines[2].startswith("    [1]")
        assert lines[3].startswith("    [2]")
        assert lines[4].startswith("    [3]")

    def test_deeply_nested(self):
        """Test multiple levels of nesting."""
        tree = {
            "role": "WebArea",
            "name": "Page",
            "children": [
                {
                    "role": "group",
                    "name": "Level 1",
                    "children": [
                        {
                            "role": "group",
                            "name": "Level 2",
                            "children": [
                                {"role": "button", "name": "Deep button"},
                            ],
                        }
                    ],
                }
            ],
        }
        transformer = SnapshotTransformer()
        text, ref_map = transformer.transform(tree)

        lines = text.split("\n")
        assert lines[0] == "Page (WebArea)"
        assert "Level 1" in lines[1]
        assert "Level 2" in lines[2]
        assert "[1] Deep button" in lines[3]


class TestDepthLimiting:
    """Test max depth behavior."""

    def test_respects_max_depth(self):
        """Should stop traversing at max depth."""
        # Create a tree deeper than max_depth
        tree = {
            "role": "WebArea",
            "children": [
                {
                    "role": "group",
                    "name": "L1",
                    "children": [
                        {
                            "role": "group",
                            "name": "L2",
                            "children": [
                                {
                                    "role": "group",
                                    "name": "L3",
                                    "children": [{"role": "button", "name": "Deep"}],
                                }
                            ],
                        }
                    ],
                }
            ],
        }

        transformer = SnapshotTransformer(max_depth=2)
        text, ref_map = transformer.transform(tree)

        # Should include L1 and L2 but not L3
        assert "L1" in text
        assert "L2" in text
        assert "L3" not in text
        assert "Deep" not in text

    def test_default_max_depth(self):
        """Default max depth should be 10."""
        transformer = SnapshotTransformer()
        assert transformer.max_depth == 10


class TestStateAnnotations:
    """Test element state annotations."""

    def test_checked_checkbox(self):
        """Checked checkbox should show state."""
        tree = {"role": "checkbox", "name": "Remember me", "checked": True}
        transformer = SnapshotTransformer()
        text, ref_map = transformer.transform(tree)

        assert "[1] Remember me (checkbox, checked)" in text

    def test_unchecked_checkbox(self):
        """Unchecked checkbox should show state."""
        tree = {"role": "checkbox", "name": "Subscribe", "checked": False}
        transformer = SnapshotTransformer()
        text, ref_map = transformer.transform(tree)

        assert "[1] Subscribe (checkbox, unchecked)" in text

    def test_disabled_button(self):
        """Disabled button should show state."""
        tree = {"role": "button", "name": "Submit", "disabled": True}
        transformer = SnapshotTransformer()
        text, ref_map = transformer.transform(tree)

        assert "[1] Submit (button, disabled)" in text

    def test_textbox_with_value(self):
        """Textbox with value should show it."""
        tree = {"role": "textbox", "name": "Email", "value": "user@example.com"}
        transformer = SnapshotTransformer()
        text, ref_map = transformer.transform(tree)

        assert '[1] Email (textbox, value: "user@example.com")' in text

    def test_textbox_empty_value(self):
        """Textbox with empty value should not show value annotation."""
        tree = {"role": "textbox", "name": "Search", "value": ""}
        transformer = SnapshotTransformer()
        text, ref_map = transformer.transform(tree)

        # Should not include value annotation for empty string
        assert "[1] Search (textbox)" in text
        assert "value:" not in text

    def test_multiple_states(self):
        """Element with multiple states should show all."""
        tree = {"role": "checkbox", "name": "Agree", "checked": True, "disabled": True}
        transformer = SnapshotTransformer()
        text, ref_map = transformer.transform(tree)

        # Should show both checked and disabled
        text_lower = text.lower()
        assert "checked" in text_lower
        assert "disabled" in text_lower


class TestEdgeCases:
    """Test edge cases and unusual inputs."""

    def test_node_without_role(self):
        """Node without role should be skipped."""
        tree = {
            "role": "WebArea",
            "children": [
                {"name": "No role"},  # Missing role
                {"role": "button", "name": "Has role"},
            ],
        }
        transformer = SnapshotTransformer()
        text, ref_map = transformer.transform(tree)

        # Node without role should be skipped but children traversed
        assert "No role" not in text
        assert "[1] Has role (button)" in text

    def test_node_without_name(self):
        """Node without name should still show role."""
        tree = {"role": "button"}  # No name
        transformer = SnapshotTransformer()
        text, ref_map = transformer.transform(tree)

        assert "[1] (button)" in text

    def test_node_without_children_key(self):
        """Node without children key should not crash."""
        tree = {"role": "button", "name": "Solo"}  # No children key
        transformer = SnapshotTransformer()
        text, ref_map = transformer.transform(tree)

        assert "[1] Solo (button)" in text

    def test_empty_children_list(self):
        """Node with empty children list should work."""
        tree = {"role": "button", "name": "Parent", "children": []}
        transformer = SnapshotTransformer()
        text, ref_map = transformer.transform(tree)

        assert "[1] Parent (button)" in text


class TestRefMapCorrectness:
    """Test that ref_map correctly points to original nodes."""

    def test_ref_map_points_to_original_nodes(self):
        """ref_map should contain references to original node dicts."""
        button_node = {"role": "button", "name": "Click"}
        link_node = {"role": "link", "name": "Nav"}
        tree = {"role": "WebArea", "children": [button_node, link_node]}

        transformer = SnapshotTransformer()
        text, ref_map = transformer.transform(tree)

        assert ref_map[1] is button_node
        assert ref_map[2] is link_node

    def test_ref_map_preserves_node_data(self):
        """ref_map nodes should have all original data."""
        tree = {
            "role": "WebArea",
            "children": [
                {
                    "role": "textbox",
                    "name": "Email",
                    "value": "test@example.com",
                    "custom_attr": "some_value",
                }
            ],
        }

        transformer = SnapshotTransformer()
        text, ref_map = transformer.transform(tree)

        node = ref_map[1]
        assert node["role"] == "textbox"
        assert node["name"] == "Email"
        assert node["value"] == "test@example.com"
        assert node["custom_attr"] == "some_value"


class TestSkipRoles:
    """Test SKIP_ROLES filtering behavior."""

    def test_generic_nodes_flattened(self):
        """Generic nodes without names should be flattened through."""
        tree = {
            "role": "WebArea",
            "name": "Page",
            "children": [
                {
                    "role": "generic",  # Should be skipped
                    "children": [
                        {
                            "role": "generic",  # Should be skipped
                            "children": [
                                {"role": "heading", "name": "SEAN DANIEL", "level": 1},
                            ],
                        }
                    ],
                }
            ],
        }
        transformer = SnapshotTransformer()
        text, ref_map = transformer.transform(tree)

        lines = text.split("\n")
        # Generic nodes should be invisible, heading should be at depth 1 (2 spaces)
        assert lines[0] == "Page (WebArea)"
        assert lines[1] == "  SEAN DANIEL (heading, level 1)"
        assert len(lines) == 2

    def test_group_without_name_flattened(self):
        """Group nodes without names should be flattened through."""
        tree = {
            "role": "WebArea",
            "children": [
                {
                    "role": "group",  # Should be skipped (no name)
                    "children": [
                        {"role": "button", "name": "Click me"},
                    ],
                }
            ],
        }
        transformer = SnapshotTransformer()
        text, ref_map = transformer.transform(tree)

        lines = text.split("\n")
        # Group should be invisible, button should be at depth 1 (2 spaces)
        assert lines[0] == "(WebArea)"
        assert lines[1] == "  [1] Click me (button)"

    def test_none_role_flattened(self):
        """Nodes with role 'none' should be flattened through."""
        tree = {
            "role": "WebArea",
            "children": [
                {
                    "role": "none",  # Should be skipped
                    "children": [
                        {"role": "link", "name": "Nav"},
                    ],
                }
            ],
        }
        transformer = SnapshotTransformer()
        text, ref_map = transformer.transform(tree)

        lines = text.split("\n")
        assert lines[0] == "(WebArea)"
        assert lines[1] == "  [1] Nav (link)"

    def test_generic_with_name_kept(self):
        """Generic nodes WITH names should be kept (meaningful context)."""
        tree = {
            "role": "WebArea",
            "children": [
                {
                    "role": "generic",
                    "name": "Navigation",  # Has name - should be kept
                    "children": [
                        {"role": "link", "name": "Home"},
                        {"role": "link", "name": "About"},
                    ],
                }
            ],
        }
        transformer = SnapshotTransformer()
        text, ref_map = transformer.transform(tree)

        lines = text.split("\n")
        # Generic with name should be visible
        assert lines[0] == "(WebArea)"
        assert lines[1] == "  Navigation (generic)"
        assert lines[2] == "    [1] Home (link)"
        assert lines[3] == "    [2] About (link)"

    def test_group_with_name_kept(self):
        """Group nodes WITH names should be kept."""
        tree = {
            "role": "WebArea",
            "children": [
                {
                    "role": "group",
                    "name": "Form Controls",  # Has name - should be kept
                    "children": [
                        {"role": "textbox", "name": "Email"},
                    ],
                }
            ],
        }
        transformer = SnapshotTransformer()
        text, ref_map = transformer.transform(tree)

        lines = text.split("\n")
        assert lines[0] == "(WebArea)"
        assert lines[1] == "  Form Controls (group)"
        assert lines[2] == "    [1] Email (textbox)"

    def test_multiple_skip_roles_flattened(self):
        """Multiple consecutive skip roles should all be flattened."""
        tree = {
            "role": "WebArea",
            "children": [
                {
                    "role": "generic",
                    "children": [
                        {
                            "role": "none",
                            "children": [
                                {
                                    "role": "group",
                                    "children": [
                                        {"role": "button", "name": "Deep Button"},
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        transformer = SnapshotTransformer()
        text, ref_map = transformer.transform(tree)

        lines = text.split("\n")
        # All three skip roles should be invisible
        assert lines[0] == "(WebArea)"
        assert lines[1] == "  [1] Deep Button (button)"
        assert len(lines) == 2


class TestRealWorldExample:
    """Test with example from sprint plan."""

    def test_sprint_plan_example(self):
        """Test the exact example from the sprint plan."""
        tree = {
            "role": "WebArea",
            "name": "Example Page",
            "children": [
                {"role": "heading", "name": "Welcome", "level": 1},
                {"role": "button", "name": "Sign In"},
                {"role": "textbox", "name": "Email", "value": ""},
                {"role": "link", "name": "Forgot password?"},
                {
                    "role": "group",
                    "name": "Options",
                    "children": [
                        {"role": "checkbox", "name": "Remember me", "checked": False},
                        {"role": "button", "name": "Submit", "disabled": True},
                    ],
                },
            ],
        }

        transformer = SnapshotTransformer()
        text, ref_map = transformer.transform(tree)

        expected_lines = [
            "Example Page (WebArea)",
            "  Welcome (heading, level 1)",
            "  [1] Sign In (button)",
            "  [2] Email (textbox)",
            "  [3] Forgot password? (link)",
            "  Options (group)",
            "    [4] Remember me (checkbox, unchecked)",
            "    [5] Submit (button, disabled)",
        ]

        actual_lines = text.split("\n")
        assert actual_lines == expected_lines

        # Verify ref map
        assert len(ref_map) == 5
        assert ref_map[1]["name"] == "Sign In"
        assert ref_map[2]["name"] == "Email"
        assert ref_map[3]["name"] == "Forgot password?"
        assert ref_map[4]["name"] == "Remember me"
        assert ref_map[5]["name"] == "Submit"
