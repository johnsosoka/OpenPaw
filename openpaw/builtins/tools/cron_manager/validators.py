"""Name/schedule/delivery validation for cron manager."""

import logging
import re

from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

# Regex for valid cron job names: alphanumeric and hyphens only.
_VALID_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class CronValidator:
    """Validates cron job names, schedules, and delivery modes."""

    @staticmethod
    def validate_name(name: str) -> str | None:
        """Return an error message if the name is invalid, otherwise None."""
        if not _VALID_NAME_RE.match(name):
            return (
                f"Invalid cron name '{name}'. "
                "Use lowercase letters, digits, and hyphens only "
                "(e.g., 'morning-check', 'daily-summary'). "
                "Must start with a letter or digit."
            )
        return None

    @staticmethod
    def validate_schedule(schedule: str) -> str | None:
        """Return an error message if the cron expression is invalid, otherwise None."""
        try:
            CronTrigger.from_crontab(schedule)
        except (ValueError, KeyError) as e:
            return f"Invalid cron expression '{schedule}': {e}"
        return None

    @staticmethod
    def validate_delivery(delivery: str) -> str | None:
        """Return an error message if the delivery mode is invalid, otherwise None."""
        allowed = {"channel", "agent"}
        if delivery not in allowed:
            return f"Invalid delivery mode '{delivery}'. Must be one of: {allowed}"
        return None


__all__ = ["CronValidator"]
