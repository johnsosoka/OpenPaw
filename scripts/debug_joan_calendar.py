#!/usr/bin/env python3
"""Debug script to test Joan's CalDAV connection and list available calendars."""

import os
import sys
from pathlib import Path

# Set up environment from Joan's .env
env_file = Path("/Users/john/code/projects/OpenPaw/agent_workspaces/joan_holloway/.env")
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                value = value.strip('"').strip("'")
                os.environ[key] = value
                print(f"Loaded: {key}")

# Add tools directory to path
tools_dir = Path("/Users/john/code/projects/OpenPaw/agent_workspaces/joan_holloway/tools")
sys.path.insert(0, str(tools_dir))

print("\n" + "="*60)
print("Testing CalDAV Connection")
print("="*60)

try:
    import caldav
    print("✓ caldav module imported")

    # Try to connect using Joan's credentials
    user = os.getenv("ICLOUD_CALDAV_USER")
    password = os.getenv("ICLOUD_CALDAV_PASS")
    principal_path = os.getenv("ICLOUD_PRINCIPAL")

    print(f"\nCredentials:")
    print(f"  User: {user}")
    print(f"  Password: {'*' * len(password) if password else 'NOT SET'}")
    print(f"  Principal: {principal_path}")

    if not all([user, password, principal_path]):
        print("\n❌ Missing credentials!")
        sys.exit(1)

    # Connect
    url = f"https://caldav.icloud.com{principal_path}/calendars/"
    print(f"\nConnecting to: {url}")

    client = caldav.DAVClient(url=url, username=user, password=password)
    principal = client.principal()
    print("✓ Connected to CalDAV")

    # List all calendars
    print("\n" + "="*60)
    print("All Calendars from principal.calendars()")
    print("="*60)

    all_calendars = principal.calendars()
    for i, cal in enumerate(all_calendars, 1):
        cal_name = cal.name or "Unknown"
        print(f"\n{i}. Name: {cal_name}")
        print(f"   URL: {cal.url}")

        # Check if it matches filter criteria
        is_reminder = "reminder" in cal_name.lower()
        is_task = "task" in cal_name.lower()
        filtered_out = is_reminder or is_task

        print(f"   Filtered: {'YES' if filtered_out else 'NO'}")
        if filtered_out:
            print(f"   Reason: {'reminder' if is_reminder else 'task'} in name")

    # Now test the actual _calendar_core.py function
    print("\n" + "="*60)
    print("Testing get_caldav_calendars() function")
    print("="*60)

    from _calendar_core import get_caldav_calendars

    calendars = get_caldav_calendars()
    print(f"\nReturned {len(calendars)} calendar(s):")
    for i, cal in enumerate(calendars, 1):
        print(f"  {i}. {cal.name or 'Unknown'}")

    # Check for expected personal calendars
    print("\n" + "="*60)
    print("Analysis")
    print("="*60)

    all_names = [cal.name for cal in all_calendars if cal.name]
    filtered_names = [cal.name for cal in calendars if cal.name]

    print(f"\nTotal calendars from iCloud: {len(all_calendars)}")
    print(f"Calendars after filtering: {len(calendars)}")
    print(f"Filtered out: {len(all_calendars) - len(calendars)}")

    print("\nCalendar names in all_calendars:")
    for name in sorted(all_names):
        print(f"  - {name}")

    print("\nCalendar names after filtering:")
    for name in sorted(filtered_names):
        print(f"  - {name}")

    # Check for missing environment variables
    print("\n" + "="*60)
    print("Write Operations Configuration")
    print("="*60)

    env_vars_needed = {
        "CALENDAR_NAME_PERSONAL": "personal",
        "CALENDAR_NAME_WIFE": "wife",
        "CALENDAR_NAME_FAMILY": "family",
    }

    print("\nEnvironment variables for write operations:")
    missing = []
    for env_var, friendly_name in env_vars_needed.items():
        value = os.getenv(env_var, "").strip()
        if value:
            print(f"  {env_var}: {value}")
        else:
            print(f"  {env_var}: NOT SET ❌")
            missing.append(env_var)

    if missing:
        print(f"\n⚠️  {len(missing)} environment variable(s) missing!")
        print("\nThis is why write operations fail. The resolve_writable_calendar()")
        print("function requires these variables to map friendly names to")
        print("actual iCloud calendar names.")

        print("\nSuggested .env additions:")
        for env_var in missing:
            friendly = env_vars_needed[env_var]
            print(f'  {env_var}="<exact iCloud calendar name for {friendly}>"')
    else:
        print("\n✓ All write operation environment variables configured")

except ImportError as e:
    print(f"❌ Failed to import required module: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
