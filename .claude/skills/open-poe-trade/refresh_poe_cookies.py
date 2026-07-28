# -*- coding: utf-8 -*-
"""Refresh .poe_cookies.json from the currently-open, logged-in POE browser.

This implements the **Refresh-on-trigger rule** in
`../poe-trade-query/common/tricks.md`: any time a headed browser is opened for
POE, the cookie cache should be re-exported so it holds the latest known-good
POESESSID + cf_clearance + the UA they were captured under. It lives in this
skill because opening the browser is what triggers the write-back.

It exists as a dedicated script so exactly one command can be put on the
permission allowlist, instead of allowing arbitrary `playwright-cli run-code`.

Usage (paths relative to the project root):
    python .claude/skills/open-poe-trade/refresh_poe_cookies.py            # refresh
    python .claude/skills/open-poe-trade/refresh_poe_cookies.py --force    # ignore downgrade guard
    python .claude/skills/open-poe-trade/refresh_poe_cookies.py --status   # report only, no write

Prereq: the browser must already be open and logged in, e.g.
    playwright-cli open --headed --persistent "https://www.pathofexile.com/"
"""
import datetime
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))          # .claude/skills/open-poe-trade
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))   # project root
CACHE = os.path.join(ROOT, ".poe_cookies.json")
EXPORT_JS = os.path.join(HERE, "export_poe_cookies.js")
NOTE = ("Cloudflare clearance + session for plain-HTTP trade API calls. "
        "cf_clearance is bound to this machine's IP + the user_agent below - "
        "always send them together. Refresh by re-running "
        ".claude/skills/open-poe-trade/refresh_poe_cookies.py while a "
        "logged-in headed browser is open.")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _playwright_cli():
    """npm global shims aren't PE executables on Windows -> use the .cmd."""
    if os.name == "nt":
        cmd = os.path.expandvars(r"%APPDATA%\npm\playwright-cli.cmd")
        if os.path.isfile(cmd):
            return cmd
    return "playwright-cli"


def export_from_browser():
    r = subprocess.run([_playwright_cli(), "--raw", "run-code", "--filename", EXPORT_JS],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
    out = (r.stdout or "").strip()
    if not out:
        raise SystemExit("no output from playwright-cli. Is the browser open?\n"
                         f"  stderr: {(r.stderr or '').strip()[:400]}")
    if "is not open" in out or "is not open" in (r.stderr or ""):
        raise SystemExit("browser session is not open. Start it with:\n"
                         '  playwright-cli open --headed --persistent "https://www.pathofexile.com/"')
    try:
        return json.loads(json.loads(out))       # --raw prints a JSON string literal
    except Exception:
        raise SystemExit(f"could not parse export output: {out[:400]}")


def main():
    force = "--force" in sys.argv
    data = export_from_browser()
    cookies = data.get("cookies") or {}
    ua = (data.get("user_agent") or "").strip()
    authed = data.get("profile_status") == 200

    print(f"browser UA        : {ua}")
    print(f"/api/profile      : {data.get('profile_status')} "
          f"({'logged in' if authed else 'NOT logged in'})")
    print(f"cookies found     : {', '.join(sorted(cookies)) or '(none)'}")

    old = {}
    if os.path.isfile(CACHE):
        try:
            old = json.load(open(CACHE, encoding="utf-8"))
        except Exception:
            pass
        print(f"existing cache    : saved_at={old.get('saved_at')} "
              f"authenticated={old.get('authenticated')}")

    if "--status" in sys.argv:
        return

    if not cookies.get("POESESSID"):
        raise SystemExit("refusing to write: no POESESSID in the browser session.")
    if not ua.startswith("Mozilla/"):
        raise SystemExit(f"refusing to write: implausible UA {ua!r}")
    # Don't trade a known-good cache for an anonymous one by accident.
    if not authed and old.get("authenticated") and not force:
        raise SystemExit("refusing to write: this browser session is NOT logged in, but the "
                         "existing cache was captured while authenticated. Log in in the "
                         "browser and retry, or pass --force to overwrite anyway.")

    payload = {
        "saved_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "authenticated": authed,
        "note": NOTE,
        "user_agent": ua,
        "cookies": cookies,
    }
    with open(CACHE, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
    # Report what actually landed on disk, so a caller never has to assume.
    written = json.load(open(CACHE, encoding="utf-8"))
    print(f"\nwrote {CACHE}")
    print(f"  saved_at={written['saved_at']} authenticated={written['authenticated']} "
          f"keys={sorted(written['cookies'])}")


if __name__ == "__main__":
    main()
