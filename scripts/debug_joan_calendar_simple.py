#!/usr/bin/env python3
"""Simple diagnostic script to test Joan's CalDAV connection."""

import os
import sys

# Set up environment from Joan's .env
with open("/Users/john/code/projects/OpenPaw/agent_workspaces/joan_holloway/.env") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            value = value.strip('"').strip("'")
            os.environ[key] = value

print("Testing CalDAV Connection")
print("="*60)

try:
    import caldav

    # Connect using Joan's credentials
    user = os.getenv("ICLOUD_CALDAV_USER")
    password = os.getenv("ICLOUD_CALDAV_PASS")
    principal_path = os.getenv("ICLOUD_PRINCIPAL")

    print(f"User: {user}")
    print(f"Principal: {principal_path}\n")

    url = f"https://caldav.icloud.com{principal_path}/calendars/"
    client = caldav.DAVClient(url=url, username=user, password=password)
    principal = client.principal()
    print("✓ Connected to CalDAV\n")

    # List all calendars
    print("All Calendars:")
    print("-"*60)
    all_calendars = principal.calendars()
    for i, cal in enumerate(all_calendars, 1):
        name = cal.name or "Unknown"
        is_reminder = "reminder" in name.lower()
        is_task = "task" in name.lower()
        filtered = " [FILTERED]" if (is_reminder or is_task) else ""
        print(f"{i}. {name}{filtered}")

    # Show filtered list
    print("\nAfter filtering (reminders/tasks removed):")
    print("-"*60)
    filtered_calendars = [cal for cal in all_calendars
                          if not ("reminder" in (cal.name or "").lower() or
                                  "task" in (cal.name or "").lower())]
    for i, cal in enumerate(filtered_calendars, 1):
        print(f"{i}. {cal.name or 'Unknown'}")

    # Check for write operation env vars
    print("\nWrite Operation Configuration:")
    print("-"*60)
    env_vars = {
        "CALENDAR_NAME_PERSONAL": "personal",
        "CALENDAR_NAME_WIFE": "wife",
        "CALENDAR_NAME_FAMILY": "family",
    }

    missing = []
    for var, friendly in env_vars.items():
        val = os.getenv(var, "")
        if val:
            print(f"✓ {var}={val}")
        else:
            print(f"✗ {var} NOT SET")
            missing.append(var)

    if missing:
        print(f"\n⚠️  {len(missing)} environment variables missing!")
        print("\nThese variables map friendly names (personal/wife/family)")
        print("to actual iCloud calendar names for write operations.")
        print("\nSuggested additions to .env:")
        for var in missing:
            friendly = env_vars[var]
            print(f'  {var}="<exact iCloud calendar name>"')

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
