"""Module registry — config key -> module class (ADR-102 §2, amended).

Adding a future module = one class + one entry in ``MODULE_REGISTRY`` (plus a
config enum value and docs). Nothing else in this package needs touching.
"""

from openpaw.agent.harness.modules.base import ModuleKind, ReasoningModule
from openpaw.agent.harness.modules.direct import DirectPlanner
from openpaw.agent.harness.modules.ideonomy import IdeonomyModule
from openpaw.agent.harness.modules.reflection import FullReflection, LightReflection
from openpaw.agent.harness.modules.self_discover import SelfDiscoverPlanner

MODULE_REGISTRY: dict[str, type[ReasoningModule]] = {
    "direct": DirectPlanner,  # PLANNING — single-call baseline
    "self_discover": SelfDiscoverPlanner,  # PLANNING — SELECT/ADAPT/IMPLEMENT + structure cache
    "ideonomy": IdeonomyModule,  # CREATIVE — ideonomic lens ideation
    "light": LightReflection,  # REFLECTION — single outcome check
    "full": FullReflection,  # REFLECTION — may rewrite remaining plan
}

# Fail-open defaults per kind (selector path 3 falls back here).
KIND_DEFAULTS: dict[ModuleKind, str] = {
    ModuleKind.PLANNING: "direct",
    ModuleKind.CREATIVE: "ideonomy",  # lands with the Phase 3 registry entry
    ModuleKind.REFLECTION: "light",
}


def get_module_class(name: str) -> type[ReasoningModule]:
    """Return the registered module class for a config key.

    Raises:
        ValueError: If the name is not registered.
    """
    try:
        return MODULE_REGISTRY[name]
    except KeyError:
        raise ValueError(f"Unknown reasoning module {name!r}; known modules: {sorted(MODULE_REGISTRY)}") from None


def candidates_for(kind: ModuleKind) -> dict[str, type[ReasoningModule]]:
    """Return all registered module classes of the given kind."""
    return {name: cls for name, cls in MODULE_REGISTRY.items() if cls.kind == kind}
