"""Codebase Cartographer — an agentic onboarding mapper built on smolagents."""

from .agents import ONBOARDING_BRIEF, build_cartographer
from .tools import set_output_dir, set_repo_root

__all__ = ["build_cartographer", "ONBOARDING_BRIEF", "set_repo_root", "set_output_dir"]
__version__ = "0.1.0"
