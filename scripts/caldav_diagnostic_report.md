# CalDAV Diagnostic Report
**Date:** 2026-02-08
**Workspace:** joan_holloway
**Issue:** Calendar tools list calendars but return zero events

---

## Executive Summary

**Root Cause Identified:** Missing `vobject` library dependency

**Status:** The hypothesis about iCloud shared calendars was **INCORRECT**. Calendars ARE returning events successfully from CalDAV, but the production code cannot parse them due to missing `vobject` library.

---

## Diagnostic Findings

### Calendar Event Retrieval Results (Feb 8-14, 2026)

| Calendar Name      | date_search(expand=True) | Status |
|-------------------|-------------------------|--------|
| Family Calendar   | 2 events                | ✓ Working |
| Bills             | 6 events                | ✓ Working |
| Family ⚠️         | 0 events                | Empty calendar |
| John's Calendar   | 1 event                 | ✓ Working |
| Anna's calendar   | 13 events               | ✓ Working |

**Key Observation:** Shared/family calendars ("Family Calendar", "Anna's calendar") ARE returning events successfully. No CalDAV API issues detected.

### Dependency Analysis

The caldav library version 2.0+ **removed vobject as an automatic dependency**. The production code in `_calendar_core.py` uses this pattern throughout:

```python
events = cal.date_search(start=start, end=end, expand=True)
for e in events:
    vevent = e.vobject_instance.vevent  # ← FAILS: vobject not installed
    event_start = vevent.dtstart.value
```

**Error seen during diagnostic:**
```
CRITICAL:root:A vobject instance has been requested, but the vobject library
is not installed (vobject is no longer an official dependency in 2.0)
```

### Verification

```bash
$ poetry run python -c "import vobject"
ModuleNotFoundError: No module named 'vobject'
```

The `vobject` library is **not installed** in the OpenPaw Poetry environment.

---

## Fix Required

Add `vobject` to Joan's workspace tools requirements:

**File:** `/Users/john/code/projects/OpenPaw/agent_workspaces/joan_holloway/tools/requirements.txt`

```diff
 # Calendar tool dependencies
 icalendar>=5.0.0
 recurring-ical-events>=2.0.0
 caldav>=1.0.0
+vobject>=0.9.0
```

Then reinstall dependencies (OpenPaw's workspace tool loader should handle this automatically on next run, or manually install with `poetry run pip install vobject`).

---

## Additional Notes

### Calendar Discovery
- 7 total calendars found in iCloud
- 2 filtered out (Reminders, Tasks)
- 5 event calendars available
- All event calendars accessible via CalDAV API

### Empty Calendar
The "Family ⚠️" calendar returns zero events for all query methods (date_search, events(), search()). This appears to be legitimately empty, not a permissions/API issue.

### Alternative Methods Tested
All query methods return consistent results:
- `date_search(expand=True)` ✓
- `date_search(expand=False)` ✓
- `events()` ✓
- `search()` with XML time-range query ✓

No evidence of iCloud CalDAV delegation/sharing issues.

---

## Recommendation

**Action:** Install `vobject` library dependency
**Priority:** High (blocks all calendar event reading functionality)
**Effort:** Minimal (single dependency add)

Once `vobject` is installed, the existing production code should work correctly without any code changes.
