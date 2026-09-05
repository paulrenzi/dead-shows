#!/usr/bin/env python3
"""Fail the daily refresh when show coverage silently collapses.

WHY THIS EXISTS:
The scraper swallows a per-state fetch failure and moves on (`FETCH FAIL {st}` ->
continue). That is the right call for one flaky state and the wrong call for
fifty: if gratefuldeadtributebands.com is down, or changes its markup, every
state parses to zero, the job commits a nearly-empty gdtb-events.json, and the
site quietly shows nothing. Nobody finds out, because a green check mark and an
empty map look identical from the outside.

Two independent guards, either of which fails the build:

  1. CANARIES  -- data/coverage-canaries.json asserts things we know are true
     about our own back yard (PA has shows; Splintered Sunlight is gigging).
     Absolute floors, so they catch a cold start as well as a regression.

  2. DROP GUARD -- compares against the previously committed gdtb-events.json
     from git. A run that loses more than DROP_TOLERANCE of the file is treated
     as broken rather than as news.

Exit codes: 0 pass, 1 coverage failure, 2 could not run the check at all.
"""
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
EVENTS = DATA / "gdtb-events.json"
CANARIES = DATA / "coverage-canaries.json"

# A real-world day-to-day swing is a few percent. 40% is a cliff, not a Tuesday.
DROP_TOLERANCE = 0.40


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def previous_committed_events():
    """The last committed gdtb-events.json, or None if unavailable."""
    try:
        out = subprocess.run(
            ["git", "show", f"HEAD:data/{EVENTS.name}"],
            cwd=ROOT, capture_output=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    try:
        return json.loads(out.stdout.decode("utf-8", errors="replace"))
    except ValueError:
        return None


def matches(show, m):
    """A show matches a canary's `match` block if it satisfies every clause present."""
    states = m.get("states")
    if states and (show.get("state") or "").upper() not in {s.upper() for s in states}:
        return False

    needles = m.get("bandContains")
    if needles:
        band = (show.get("band") or "").lower()
        if not any(n.lower() in band for n in needles):
            return False

    cities = m.get("citiesContain")
    if cities:
        city = (show.get("city") or "").lower()
        if not any(c.lower() in city for c in cities):
            return False

    return True


def in_horizon(show, today, horizon_days):
    """Upcoming shows only. A canary must not be satisfied by last year's data."""
    raw = show.get("date")
    if not raw:
        return False
    try:
        d = date.fromisoformat(raw)
    except ValueError:
        return False
    return today <= d <= today + timedelta(days=horizon_days)


def main():
    if not EVENTS.exists():
        print(f"FATAL: {EVENTS} does not exist -- the scrape step did not produce a file.",
              file=sys.stderr)
        return 2
    if not CANARIES.exists():
        print(f"FATAL: {CANARIES} is missing; refusing to pass an unchecked run.",
              file=sys.stderr)
        return 2

    try:
        shows = load_json(EVENTS)
        spec = load_json(CANARIES)
    except ValueError as e:
        print(f"FATAL: could not parse coverage inputs: {e}", file=sys.stderr)
        return 2

    if not isinstance(shows, list):
        print("FATAL: gdtb-events.json is not a JSON array.", file=sys.stderr)
        return 2

    today = date.today()
    horizon = int(spec.get("horizonDays", 120))
    failures = []

    print(f"Coverage check -- {len(shows)} shows in file, horizon {horizon}d from {today}\n")

    # --- Guard 1: canaries -------------------------------------------------
    for c in spec.get("canaries", []):
        m = c.get("match", {})
        hits = [s for s in shows if in_horizon(s, today, horizon) and matches(s, m)]
        need = int(c.get("minShows", 1))
        ok = len(hits) >= need
        print(f"  [{'PASS' if ok else 'FAIL'}] {c['id']}: {len(hits)} upcoming (need >= {need})")
        if not ok:
            failures.append(f"{c['id']}: found {len(hits)}, need >= {need}. {c.get('why', '')}")

    # --- Guard 2: drop vs. the last committed file --------------------------
    prev = previous_committed_events()
    if prev is None:
        print("\n  [SKIP] drop guard: no previous committed gdtb-events.json to compare against.")
    else:
        before, after = len(prev), len(shows)
        if before == 0:
            print("\n  [SKIP] drop guard: previous file was empty.")
        else:
            delta = (after - before) / before
            print(f"\n  [{'PASS' if delta >= -DROP_TOLERANCE else 'FAIL'}] drop guard: "
                  f"{before} -> {after} ({delta:+.1%}, tolerance -{DROP_TOLERANCE:.0%})")
            if delta < -DROP_TOLERANCE:
                failures.append(
                    f"show count fell {before} -> {after} ({delta:+.1%}), beyond the "
                    f"-{DROP_TOLERANCE:.0%} tolerance. Treating as a broken scrape, not as news."
                )

    if failures:
        print("\nCOVERAGE CHECK FAILED:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        print("\nThe scraped data was NOT committed. Investigate before re-running:\n"
              "  - is gratefuldeadtributebands.com up, and has its table markup changed?\n"
              "  - did Nominatim start rate-limiting (every geocode returning None drops every show)?\n"
              "  - re-run locally: python scripts/scrape_gdtb.py && python scripts/check_coverage.py",
              file=sys.stderr)
        return 1

    print("\nCoverage OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
