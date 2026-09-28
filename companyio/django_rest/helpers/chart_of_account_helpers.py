"""
Chart of accounts helpers.

This module has been refactored. All chart of accounts categories are now
organized in separate files within the chart_of_accounts subdirectory.

For backward compatibility, this module re-exports chart_of_accounts.
"""

from .chart_of_accounts import chart_of_accounts

__all__ = ["chart_of_accounts"]
