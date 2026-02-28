"""Tests for check_unexpanded_vars validation."""

import pytest

from openpaw.core.config.loader import check_unexpanded_vars


class TestCheckUnexpandedVars:
    """Tests for unresolved ${VAR} pattern detection."""

    def test_no_vars_passes(self):
        """Fully expanded config raises nothing."""
        data = {"key": "value", "nested": {"inner": "resolved"}}
        check_unexpanded_vars(data, source="test.yaml")

    def test_simple_string_passes(self):
        """Plain strings with no ${} patterns pass."""
        check_unexpanded_vars("just a string", source="test.yaml")

    def test_unresolved_var_raises(self):
        """Single unresolved ${VAR} raises ValueError."""
        data = {"api_key": "${MISSING_KEY}"}
        with pytest.raises(ValueError, match="MISSING_KEY"):
            check_unexpanded_vars(data, source="test.yaml")

    def test_source_label_in_error(self):
        """Error message includes the source label."""
        data = {"key": "${MISSING}"}
        with pytest.raises(ValueError, match="config.yaml"):
            check_unexpanded_vars(data, source="config.yaml")

    def test_nested_dict_detection(self):
        """Unresolved var in nested dict is detected."""
        data = {"outer": {"inner": {"deep": "${DEEP_VAR}"}}}
        with pytest.raises(ValueError, match="DEEP_VAR"):
            check_unexpanded_vars(data, source="test.yaml")

    def test_list_detection(self):
        """Unresolved var in list is detected."""
        data = {"items": ["ok", "${MISSING_ITEM}"]}
        with pytest.raises(ValueError, match="MISSING_ITEM"):
            check_unexpanded_vars(data, source="test.yaml")

    def test_multiple_unresolved_vars(self):
        """Multiple unresolved vars are all reported."""
        data = {"a": "${VAR_A}", "b": "${VAR_B}"}
        with pytest.raises(ValueError, match="VAR_A") as exc_info:
            check_unexpanded_vars(data, source="test.yaml")
        assert "VAR_B" in str(exc_info.value)

    def test_none_value_passes(self):
        """None values do not cause errors."""
        data = {"key": None}
        check_unexpanded_vars(data, source="test.yaml")

    def test_numeric_value_passes(self):
        """Numeric values do not cause errors."""
        data = {"port": 8080, "ratio": 0.5}
        check_unexpanded_vars(data, source="test.yaml")

    def test_bool_value_passes(self):
        """Boolean values do not cause errors."""
        data = {"enabled": True}
        check_unexpanded_vars(data, source="test.yaml")

    def test_empty_dict_passes(self):
        """Empty dict raises nothing."""
        check_unexpanded_vars({}, source="test.yaml")

    def test_empty_list_passes(self):
        """Empty list raises nothing."""
        check_unexpanded_vars([], source="test.yaml")

    def test_mixed_resolved_and_unresolved(self):
        """Only unresolved vars are reported, resolved ones pass."""
        data = {"good": "resolved_value", "bad": "${UNSET_VAR}"}
        with pytest.raises(ValueError, match="UNSET_VAR"):
            check_unexpanded_vars(data, source="test.yaml")

    def test_partial_expansion_detected(self):
        """Partially expanded string like 'prefix_${VAR}_suffix' is caught."""
        data = {"url": "https://api.example.com/${API_VERSION}/endpoint"}
        with pytest.raises(ValueError, match="API_VERSION"):
            check_unexpanded_vars(data, source="test.yaml")
