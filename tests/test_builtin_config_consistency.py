"""Consistency tests for the single-sourced builtin config fields (PRD-003 S-A3).

BUILTIN_CONFIG_FIELDS in core/config/models/builtin.py is the single source of
truth for typed per-builtin field extraction. These tests enforce that:

- BuiltinsConfig and WorkspaceBuiltinsConfig mirror the same per-builtin
  fields with the same model types (Workspace = Optional variant).
- BUILTIN_CONFIG_FIELDS only references declared builtins and real fields.
- BuiltinLoader._CONFIG_FIELDS is derived from the shared map, not a copy.
"""

import typing

from openpaw.builtins.loader import BuiltinLoader
from openpaw.core.config.models.builtin import (
    BUILTIN_CONFIG_FIELDS,
    BuiltinItemConfig,
    BuiltinsConfig,
    WorkspaceBuiltinsConfig,
)


def _per_builtin_fields(model_cls: type) -> dict[str, type]:
    """Map field name -> builtin config model type for per-builtin fields.

    A per-builtin field is one whose annotation is a BuiltinItemConfig
    subclass (global form) or an Optional thereof (workspace form).
    """
    result: dict[str, type] = {}
    for name, field_info in model_cls.model_fields.items():
        annotation = field_info.annotation
        candidates = [annotation, *typing.get_args(annotation)]
        for candidate in candidates:
            if isinstance(candidate, type) and issubclass(candidate, BuiltinItemConfig):
                result[name] = candidate
                break
    return result


class TestBuiltinConfigMirrorConsistency:
    def test_global_and_workspace_field_sets_match(self):
        """Both classes declare exactly the same per-builtin field names."""
        global_fields = _per_builtin_fields(BuiltinsConfig)
        workspace_fields = _per_builtin_fields(WorkspaceBuiltinsConfig)
        assert global_fields.keys() == workspace_fields.keys()

    def test_global_and_workspace_field_types_match(self):
        """Each mirrored field uses the same builtin config model type."""
        global_fields = _per_builtin_fields(BuiltinsConfig)
        workspace_fields = _per_builtin_fields(WorkspaceBuiltinsConfig)
        for name, global_type in global_fields.items():
            assert workspace_fields[name] is global_type, name

    def test_workspace_fields_default_to_none(self):
        """Workspace overrides are Optional with default None."""
        for name in _per_builtin_fields(WorkspaceBuiltinsConfig):
            field_info = WorkspaceBuiltinsConfig.model_fields[name]
            assert field_info.default is None, name


class TestBuiltinConfigFieldsMap:
    def test_keys_are_declared_builtins(self):
        """Every mapped builtin is a declared field on BuiltinsConfig."""
        declared = _per_builtin_fields(BuiltinsConfig)
        for name in BUILTIN_CONFIG_FIELDS:
            assert name in declared, f"'{name}' not declared on BuiltinsConfig"

    def test_field_names_exist_on_models(self):
        """Every listed field exists on the corresponding config model."""
        declared = _per_builtin_fields(BuiltinsConfig)
        for name, fields in BUILTIN_CONFIG_FIELDS.items():
            model_cls = declared[name]
            for field_name in fields:
                assert field_name in model_cls.model_fields, (
                    f"'{field_name}' not a field on {model_cls.__name__}"
                )

    def test_field_names_are_not_base_fields(self):
        """Listed fields are builtin-specific, not inherited base fields."""
        base_fields = set(BuiltinItemConfig.model_fields)
        for name, fields in BUILTIN_CONFIG_FIELDS.items():
            overlap = base_fields.intersection(fields)
            assert not overlap, f"'{name}' lists base fields: {overlap}"

    def test_loader_map_is_the_shared_map(self):
        """BuiltinLoader derives its map from the single source (no copy)."""
        assert BuiltinLoader._CONFIG_FIELDS is BUILTIN_CONFIG_FIELDS
