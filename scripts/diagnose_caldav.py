#!/usr/bin/env python3
"""
Run this script with:
  poetry run python scripts/diagnose_caldav.py

OR install dependencies manually:
  pip install --user caldav lxml
  python3 scripts/diagnose_caldav.py
"""
"""CalDAV diagnostic script for investigating iCloud shared calendar issues.

This script tests various methods of accessing calendar events to determine
why shared/family calendars return zero events via date_search().

Hypothesis: iCloud CalDAV shared/family calendars are discoverable but
date_search() returns empty due to delegation/sharing permissions.
"""
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

# Import dependencies first
try:
    import caldav
except ImportError:
    print("ERROR: caldav package not installed")
    print("\nPlease run one of:")
    print("  poetry run python scripts/diagnose_caldav.py")
    print("  pip install --user caldav lxml && python3 scripts/diagnose_caldav.py")
    sys.exit(1)

# Add the workspace tools directory to the path for imports
workspace_path = "/Users/john/code/projects/OpenPaw/agent_workspaces/joan_holloway"
tools_path = os.path.join(workspace_path, "tools")
sys.path.insert(0, tools_path)

# Load .env file
from pathlib import Path
env_file = Path(workspace_path) / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key] = value.strip('"').strip("'")


def print_section(title: str):
    """Print a formatted section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def connect_to_icloud():
    """Connect to iCloud CalDAV and return the principal."""
    user = os.getenv("ICLOUD_CALDAV_USER")
    password = os.getenv("ICLOUD_CALDAV_PASS")
    principal_path = os.getenv("ICLOUD_PRINCIPAL")

    if not all([user, password, principal_path]):
        print("ERROR: Missing iCloud CalDAV credentials in .env")
        print(f"  ICLOUD_CALDAV_USER: {'✓' if user else '✗'}")
        print(f"  ICLOUD_CALDAV_PASS: {'✓' if password else '✗'}")
        print(f"  ICLOUD_PRINCIPAL: {'✓' if principal_path else '✗'}")
        sys.exit(1)

    print(f"Connecting to iCloud CalDAV...")
    print(f"  User: {user}")
    print(f"  Principal: {principal_path}")

    url = f"https://caldav.icloud.com{principal_path}/calendars/"
    client = caldav.DAVClient(url=url, username=user, password=password)
    principal = client.principal()

    print("✓ Connection successful")
    return principal


def get_calendar_properties(cal):
    """Extract and display calendar properties."""
    props = {}

    # Basic properties
    props["name"] = cal.name or "Unknown"
    props["url"] = str(cal.url) if hasattr(cal, "url") else "N/A"
    props["id"] = str(cal.id) if hasattr(cal, "id") else "N/A"

    # Try to get calendar type/component-set
    try:
        # CalDAV SUPPORTED-CALENDAR-COMPONENT-SET property
        if hasattr(cal, "get_property"):
            try:
                comp_set = cal.get_property("{urn:ietf:params:xml:ns:caldav}supported-calendar-component-set")
                props["component_set"] = str(comp_set) if comp_set else "N/A"
            except Exception:
                props["component_set"] = "N/A"
    except Exception:
        props["component_set"] = "N/A"

    # Try to get calendar description
    try:
        if hasattr(cal, "get_property"):
            try:
                desc = cal.get_property("{urn:ietf:params:xml:ns:caldav}calendar-description")
                props["description"] = str(desc) if desc else "N/A"
            except Exception:
                props["description"] = "N/A"
    except Exception:
        props["description"] = "N/A"

    # Try to get access control
    try:
        if hasattr(cal, "get_property"):
            try:
                acl = cal.get_property("{DAV:}current-user-privilege-set")
                props["privileges"] = str(acl) if acl else "N/A"
            except Exception:
                props["privileges"] = "N/A"
    except Exception:
        props["privileges"] = "N/A"

    return props


def test_date_search(cal, start, end, expand=True):
    """Test date_search on a calendar and return event count + first event."""
    try:
        events = cal.date_search(start=start, end=end, expand=expand)
        event_count = len(events)

        first_event_summary = None
        if event_count > 0:
            try:
                vevent = events[0].vobject_instance.vevent
                first_event_summary = str(vevent.summary.value) if hasattr(vevent, "summary") else "No title"
            except Exception as e:
                first_event_summary = f"[Error reading: {e}]"

        return event_count, first_event_summary
    except Exception as e:
        return None, f"ERROR: {e}"


def test_events_method(cal):
    """Test cal.events() method as an alternative to date_search."""
    try:
        events = cal.events()
        event_count = len(events)

        first_event_summary = None
        if event_count > 0:
            try:
                vevent = events[0].vobject_instance.vevent
                first_event_summary = str(vevent.summary.value) if hasattr(vevent, "summary") else "No title"
            except Exception as e:
                first_event_summary = f"[Error reading: {e}]"

        return event_count, first_event_summary
    except Exception as e:
        return None, f"ERROR: {e}"


def test_search_method(cal, start, end):
    """Test cal.search() method with XML query as an alternative."""
    try:
        # Build a basic time-range query
        from lxml import etree

        # Format dates for CalDAV query
        start_str = start.strftime("%Y%m%dT%H%M%SZ")
        end_str = end.strftime("%Y%m%dT%H%M%SZ")

        # Build query XML
        query = f"""<?xml version="1.0" encoding="UTF-8"?>
<C:calendar-query xmlns:C="urn:ietf:params:xml:ns:caldav" xmlns:D="DAV:">
  <D:prop>
    <D:getetag/>
    <C:calendar-data/>
  </D:prop>
  <C:filter>
    <C:comp-filter name="VCALENDAR">
      <C:comp-filter name="VEVENT">
        <C:time-range start="{start_str}" end="{end_str}"/>
      </C:comp-filter>
    </C:comp-filter>
  </C:filter>
</C:calendar-query>"""

        # Try the search
        if hasattr(cal, "search"):
            results = cal.search(query)
            event_count = len(results) if results else 0

            first_event_summary = None
            if event_count > 0:
                try:
                    vevent = results[0].vobject_instance.vevent
                    first_event_summary = str(vevent.summary.value) if hasattr(vevent, "summary") else "No title"
                except Exception as e:
                    first_event_summary = f"[Error reading: {e}]"

            return event_count, first_event_summary
        else:
            return None, "search() method not available"
    except Exception as e:
        return None, f"ERROR: {e}"


def main():
    """Main diagnostic routine."""
    print_section("iCloud CalDAV Diagnostic Tool")

    # Connect to iCloud
    try:
        principal = connect_to_icloud()
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        sys.exit(1)

    # Get timezone
    tz_str = os.getenv("TZ", "America/Boise")
    tz = ZoneInfo(tz_str)
    print(f"  Timezone: {tz_str}")

    # Define date range (Feb 8-14, 2026)
    start_date = datetime(2026, 2, 8, 0, 0, 0, tzinfo=tz)
    end_date = datetime(2026, 2, 14, 23, 59, 59, tzinfo=tz)
    print(f"  Date range: {start_date.date()} to {end_date.date()}")

    # Get all calendars
    print_section("Discovering Calendars")
    try:
        all_calendars = principal.calendars()
        print(f"Found {len(all_calendars)} calendar(s)")
    except Exception as e:
        print(f"✗ Failed to list calendars: {e}")
        sys.exit(1)

    # Filter out reminders/tasks
    calendars = []
    for cal in all_calendars:
        cal_name = cal.name or "Unknown"
        if "reminder" in cal_name.lower() or "task" in cal_name.lower():
            print(f"  - Skipping: {cal_name} (reminders/tasks)")
            continue
        calendars.append(cal)
        print(f"  + Found: {cal_name}")

    print(f"\n{len(calendars)} calendar(s) to test")

    # Test each calendar
    results = []
    for i, cal in enumerate(calendars, 1):
        cal_name = cal.name or "Unknown"
        print_section(f"Calendar {i}/{len(calendars)}: {cal_name}")

        # Get properties
        print("Properties:")
        props = get_calendar_properties(cal)
        for key, value in props.items():
            # Truncate long values
            if len(str(value)) > 100:
                value = str(value)[:97] + "..."
            print(f"  {key}: {value}")

        # Test 1: date_search with expand=True
        print("\nTest 1: date_search(expand=True)")
        count1, first1 = test_date_search(cal, start_date, end_date, expand=True)
        if count1 is not None:
            print(f"  Result: {count1} event(s)")
            if first1:
                print(f"  First event: {first1}")
        else:
            print(f"  {first1}")

        # Test 2: date_search with expand=False
        print("\nTest 2: date_search(expand=False)")
        count2, first2 = test_date_search(cal, start_date, end_date, expand=False)
        if count2 is not None:
            print(f"  Result: {count2} event(s)")
            if first2:
                print(f"  First event: {first2}")
        else:
            print(f"  {first2}")

        # Test 3: events() method
        print("\nTest 3: cal.events()")
        count3, first3 = test_events_method(cal)
        if count3 is not None:
            print(f"  Result: {count3} event(s) (all time)")
            if first3:
                print(f"  First event: {first3}")
        else:
            print(f"  {first3}")

        # Test 4: search() with XML query
        print("\nTest 4: cal.search() with XML time-range query")
        count4, first4 = test_search_method(cal, start_date, end_date)
        if count4 is not None:
            print(f"  Result: {count4} event(s)")
            if first4:
                print(f"  First event: {first4}")
        else:
            print(f"  {first4}")

        results.append({
            "name": cal_name,
            "expand_true": count1,
            "expand_false": count2,
            "events": count3,
            "search": count4,
        })

    # Summary
    print_section("Summary")
    print(f"\n{'Calendar':<25} {'expand=T':<10} {'expand=F':<10} {'events()':<10} {'search()':<10}")
    print("-" * 80)
    for r in results:
        def fmt(v):
            if v is None:
                return "ERROR"
            return str(v)

        print(f"{r['name']:<25} {fmt(r['expand_true']):<10} {fmt(r['expand_false']):<10} {fmt(r['events']):<10} {fmt(r['search']):<10}")

    print_section("Analysis")

    # Check for calendars with zero events
    zero_calendars = [r for r in results if r["expand_true"] == 0]
    if zero_calendars:
        print("\n⚠️  Calendars returning ZERO events via date_search(expand=True):")
        for r in zero_calendars:
            print(f"  - {r['name']}")

            # Check if alternative methods work
            if r["expand_false"] and r["expand_false"] > 0:
                print(f"    → expand=False returns {r['expand_false']} events (workaround!)")
            if r["events"] and r["events"] > 0:
                print(f"    → events() returns {r['events']} events (workaround!)")
            if r["search"] and r["search"] > 0:
                print(f"    → search() returns {r['search']} events (workaround!)")

    # Check for working calendars
    working_calendars = [r for r in results if r["expand_true"] and r["expand_true"] > 0]
    if working_calendars:
        print("\n✓ Calendars returning events via date_search(expand=True):")
        for r in working_calendars:
            print(f"  - {r['name']}: {r['expand_true']} events")

    print("\n" + "=" * 80)
    print("Diagnostic complete!")


if __name__ == "__main__":
    main()
