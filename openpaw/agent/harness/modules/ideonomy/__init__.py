"""Ideonomy creative reasoning module (ADR-102 §3).

Division data in ``divisions.py``; deterministic lens selection in
``selector.py``; the LLM pipeline in ``module.py``. Attribution: Patrick
Gunkel (https://ideonomy.mit.edu) and the MIT-licensed
https://github.com/Morpheis/ideonomy-engine.
"""

from openpaw.agent.harness.modules.ideonomy.module import IdeonomyModule
from openpaw.agent.harness.modules.ideonomy.selector import select_lenses

__all__ = ["IdeonomyModule", "select_lenses"]
