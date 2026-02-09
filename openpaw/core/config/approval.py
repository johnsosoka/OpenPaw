"""Configuration models for approval gates.

This module re-exports approval-related configuration models from models.py.
This separation provides a cleaner import path for approval-specific config.
"""

from openpaw.core.config.models import ApprovalGatesConfig, ToolApprovalConfig

__all__ = ["ApprovalGatesConfig", "ToolApprovalConfig"]
