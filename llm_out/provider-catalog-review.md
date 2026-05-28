# Code Review: feature/provider-catalog

**Reviewer:** Code Reviewer (Claude Sonnet 4.6)
**Branch:** `feature/provider-catalog`
**Date:** 2026-03-03
**Status:** Uncommitted working tree changes

---

## Summary

This feature introduces a global "Provider Catalog" to OpenPaw, allowing users to define provider connection details (api_key, base_url, region, etc.) once in `config.yaml` and reference them by name from workspace `agent.yaml` files. The design is sound and backward compatibility is preserved. All 1569 tests pass and ruff reports no lint errors.

There is one correctness bug and one documentation inaccuracy that must be fixed before merge. There are also a few minor code quality issues worth addressing.

---

## Verdict: Needs Changes (one bug, one doc error)

---

## 1. Correctness

### BUG: `_reset_model` uses workspace api_key instead of catalog api_key

**File:** `/Users/john/code/projects/OpenPaw/openpaw/channels/commands/handlers/model.py`, lines 108-113

```python
factory.clear_runtime_override()
resolved = factory._resolve_for_model(factory._configured_model)
context.agent_runner.update_model(
    model=resolved.model_str,
    api_key=factory._api_key,   # BUG: uses workspace-level key, not catalog key
)
```

The `_reset_model` method correctly resolves the model string through the catalog (`resolved.model_str` will be `"openai:kimi-k2.5"` for a `"moonshot:kimi-k2.5"` configured model). However, it hardcodes `factory._api_key` as the API key. When the only API key exists in the catalog entry (i.e., `workspace api_key is None`), this passes `None` to `update_model`, which will cause authentication failures at the next agent invocation.

Compare with `_switch_model` on line 132, which correctly calls `factory._resolve_api_key(model_str)` — that method checks the catalog first.

**Fix:** Replace `factory._api_key` with `factory._resolve_api_key(factory._configured_model)`:

```python
factory.clear_runtime_override()
resolved = factory._resolve_for_model(factory._configured_model)
context.agent_runner.update_model(
    model=resolved.model_str,
    api_key=factory._resolve_api_key(factory._configured_model),  # fixed
)
```

**Why the bug went undetected:** The test `test_reset_model_passes_resolved_model_str_to_runner` passes `api_key="moon-key"` to the factory that equals the catalog's `api_key="moon-key"`, so `factory._api_key == resolved.api_key` and the wrong code path is never exercised. A test with `api_key=None` on the factory and `api_key="catalog-only-key"` in the catalog would catch it.

---

### Resolution logic is correct

`resolve_provider()` in `providers.py` correctly handles all cases:
- No colon in model string → pass-through unchanged
- Unknown provider name → pass-through unchanged (backward compatibility preserved)
- Known provider with `type` field → remaps LangChain type while preserving display name
- `exclude_none=True` on `model_dump` correctly omits `None`-valued fields from `extra_kwargs`

The `AgentFactory._resolve_for_model()` / `create_agent()` / `create_stateless_agent()` wiring is correct. The `extras` merge order (`{**resolved.extra_kwargs, **self._extra_model_kwargs}`) correctly lets workspace-level kwargs override catalog-level defaults.

---

### API key precedence is catalog-first (undocumented design)

In `create_agent()` (lines 234-238):

```python
api_key = (
    resolved.api_key
    if resolved.api_key is not None
    else (self._resolve_api_key(raw_model) if self._runtime_override else self._api_key)
)
```

The catalog API key takes precedence over the workspace-configured API key. This is reasonable behavior (catalog is the authoritative source), but it's the opposite of what the documentation claims (see Section 3 below).

---

## 2. Documentation Inaccuracy

**File:** `/Users/john/code/projects/OpenPaw/CLAUDE.md`

The "Key Behaviors" bullet states:

> Workspace inline `api_key` → overrides catalog value

This is **incorrect**. The implementation has the opposite precedence: if the catalog entry has an `api_key`, it wins. The workspace-level `api_key` is only used as a fallback when the catalog entry has no `api_key`.

The correct statement should read:

> Catalog `api_key` takes precedence; workspace inline `api_key` is used as fallback when the catalog entry has none.

This should be corrected before merge to avoid user confusion when they set both a workspace `api_key` and a catalog `api_key` and wonder why the workspace one is being ignored.

---

## 3. Code Quality

### Minor: `_reset_model` and `_switch_model` access private attributes directly

**File:** `/Users/john/code/projects/OpenPaw/openpaw/channels/commands/handlers/model.py`, lines 53, 74, 109, 112, 131, 132

The command handler directly accesses `factory._provider_catalog`, `factory._configured_model`, `factory._api_key`, and `factory._resolve_for_model()`. These are intended as internal factory implementation details. The `_show_current` and `_list_providers` methods use `getattr(factory, "_provider_catalog", None)` as a defensive guard, which is already a smell — it implies the attribute is not part of the stable interface.

This is pre-existing debt that predates this PR (`_api_key`, `_configured_model` accesses were already there). The PR adds `_provider_catalog` and `_resolve_for_model()` to the set of accessed internals. The correct fix is to expose the necessary information via public properties on `AgentFactory`. For now, at minimum `_resolve_for_model` should be made public as `resolve_for_model`, since it is now called by the command handler as part of reset/switch logic.

This is not a blocker but should be tracked as technical debt.

---

### Minor: `_provider_catalog` is accessed via `getattr` as a guard in two places

**File:** `/Users/john/code/projects/OpenPaw/openpaw/channels/commands/handlers/model.py`, lines 53, 74

```python
catalog = getattr(factory, "_provider_catalog", None)
```

Since `_provider_catalog` is always set in `AgentFactory.__init__` (line 84) — `provider_catalog or {}` — this guard is unnecessary. If the attribute is accessed, it will always exist. The `getattr` pattern implies the attribute might not exist, which is misleading. Use direct attribute access once `_provider_catalog` is made a public property.

---

### Minor: Blank line inconsistency in `models.py`

**File:** `/Users/john/code/projects/OpenPaw/openpaw/core/config/models.py`, lines 33-34

```python
class LaneConfig(BaseModel):
    ...



class AgentConfig(BaseModel):
```

There are two blank lines between `LaneConfig` and `AgentConfig` (lines 32-35 in context), but the new `ProviderDefinition` class is added with the standard two blank lines separator. The extra blank line between `LaneConfig` and `AgentConfig` is pre-existing noise. Not introduced by this PR, but worth a cleanup in the vicinity of changes.

---

### Minor: `cli_init.py` shorthand comment is misleading

**File:** `/Users/john/code/projects/OpenPaw/openpaw/cli_init.py`, lines 202-207

```python
# For well-known native providers, hint at the shorthand alternative.
if provider in _PROVIDER_API_KEY_ENV:
    lines += [
        "",
        "# Or use shorthand with a configured provider:",
        f"# model: {provider}:{model_id}",
    ]
```

The comment says "Or use shorthand with a **configured provider**" and generates `# model: anthropic:claude-sonnet-4-20250514`. But this is the current format the user already used — it's not a shorthand alternative to an explicit model block. The comment will only make sense after a user has added that provider to their `config.yaml` providers catalog.

The confusion: the scaffold outputs `model: { provider: anthropic, model: claude-sonnet-4-20250514 }` as the active section, then comments out `# model: anthropic:claude-sonnet-4-20250514` as "shorthand". But that shorthand only works as a catalog reference once the user defines `anthropic:` in `config.yaml`. For native LangChain providers (anthropic, openai), the shorthand `anthropic:claude-sonnet-4-20250514` in `agent.yaml` currently also works without any catalog entry due to `WorkspaceConfig.coerce_model_string` splitting it and `resolve_provider` passing it through unchanged. This dual behavior is actually correct and useful, but the comment text is ambiguous.

Suggestion: update comment to `"# Or use catalog shorthand (requires providers.anthropic in config.yaml):"` or simply `"# Shorthand equivalent:"`.

---

## 4. Test Coverage

### Good: Core coverage is solid

`test_provider_catalog.py` is well-structured with 24 tests covering:
- All `resolve_provider()` edge cases (unknown provider, no colon, empty catalog, None fields)
- `Config` model parsing with the new `providers` field
- `AgentFactory` integration including extra_kwargs merge, workspace override semantics, and stateless agent isolation

### Issue: The `_reset_model` api_key bug has no test coverage

As described in Section 1, the test `test_reset_model_passes_resolved_model_str_to_runner` passes equal values for both `api_key` and the catalog's `api_key`, masking the bug. A test should be added:

```python
async def test_reset_model_uses_catalog_api_key_not_workspace_key():
    """_reset_model must pass catalog api_key, not workspace api_key, to update_model."""
    catalog = {"moonshot": ProviderDefinition(type="openai", api_key="catalog-only-key")}
    with patch.object(AgentRunner, "__init__", return_value=None):
        fact = AgentFactory(
            workspace=MagicMock(),
            model="moonshot:kimi-k2.5",
            api_key=None,             # workspace has no key
            ...
            provider_catalog=catalog,
        )

    fact.set_runtime_override(RuntimeModelOverride(model="anthropic:claude-test"))
    context = make_context(fact)

    await ModelCommand().handle(Mock(), "reset", context)

    call_kwargs = context.agent_runner.update_model.call_args
    assert call_kwargs[1]["api_key"] == "catalog-only-key"  # catalog key, not None
```

### Minor: `test_workspace_command_integration.py` tests assert `expected_commands` subset but not `model`

**File:** `/Users/john/code/projects/OpenPaw/tests/test_workspace_command_integration.py`, line 148

```python
expected_commands = {"start", "new", "help", "queue", "status"}
assert expected_commands.issubset(command_names)
```

The `/model` command is not included in `expected_commands`. Since this PR adds `/model list` functionality, it would be appropriate to add `"model"` to the assertion to ensure it is registered. This is not a critical gap since `test_model_command.py` tests the handler independently, but at the integration level the command registration check should be exhaustive.

---

## 5. Architecture

The design is clean and follows the project's established patterns:

- `ProviderDefinition` is a pure Pydantic model in the models layer — correct
- `resolve_provider()` is a pure function with no side effects — correct
- `ResolvedProvider` is a frozen dataclass — correct (immutable value object)
- Catalog resolution is confined to `AgentFactory` — it does not leak into `WorkspaceRunner`, channels, or schedulers — correct
- `Config.providers` defaults to `{}` — correct (backward compatibility)
- The `extra="allow"` on `ProviderDefinition` correctly enables arbitrary provider-specific kwargs to flow through to `extra_kwargs`

The only architectural concern is the pre-existing pattern of command handlers directly accessing private factory attributes. This PR extends that pattern with `_resolve_for_model`. The fix (exposing a public method) should be done as a follow-up, not a blocker.

---

## 6. Changes Outside the Feature Scope

### `cli.py`: Root `.env` loaded before `load_config`

**File:** `/Users/john/code/projects/OpenPaw/openpaw/cli.py`, lines 70-73

```python
# Load project-root .env (next to config file) before config parsing
# so that ${VAR} references in config.yaml (e.g., providers section) resolve.
root_env = args.config.parent / ".env"
if root_env.exists():
    load_dotenv(root_env, override=False)
```

This is correct and necessary. Without it, `${MOONSHOT_API_KEY}` in `config.yaml`'s `providers` section would fail with an "Unresolved environment variable" error. The `override=False` is appropriate — workspace `.env` files loaded later should take precedence. This is a clean addition.

### `cli_init.py`: New workspace scaffold with 5-directory layout

This is straightforward scaffold code. The `_parse_model_string` / `_build_agent_yaml` / `_validate_workspace_name` functions are well-structured with clear single responsibilities. The validation logic correctly handles Bedrock model IDs with multiple colons by using `partition(":")` instead of `split(":", 1)`.

---

## Summary of Required Changes

| Priority | File | Issue |
|----------|------|-------|
| **Must Fix** | `openpaw/channels/commands/handlers/model.py:112` | `_reset_model` passes `factory._api_key` instead of `factory._resolve_api_key(factory._configured_model)`, breaking catalog-api-key-only workspaces on model reset |
| **Must Fix** | `CLAUDE.md` | States "Workspace inline api_key overrides catalog value" — actual behavior is the opposite: catalog api_key takes precedence |
| Should Add | `tests/test_model_command.py` | Test `_reset_model` with `api_key=None` on factory and catalog-only api_key to catch the bug |
| Should Fix | `tests/test_workspace_command_integration.py:148` | Add `"model"` to `expected_commands` set |
| Track as Debt | `openpaw/channels/commands/handlers/model.py` | Command handler accesses private factory internals; expose `resolve_for_model` as a public method |
| Minor | `openpaw/cli_init.py:202-207` | Clarify the shorthand comment in the scaffold to reduce user confusion |
