"""Build-name registry: how a researcher reports a new build to the controller. Python 3.8+, stdlib only.

    python registry.py register --unit A --name <name> --purpose "<what this build is meant to test>"
    python registry.py list --unit A
    python registry.py path --unit A --name <name>      # where that build's file must be saved

A unit may only save builds under names it has registered, at the path printed by `path`.
Names are unique across all units; a refused name tells you nothing about who holds it.
"""
import argparse, io, json, os, re, sys, time

LAB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(LAB, "_control", "registry.json")
LOCKF = REG + ".lock"
MAX_BUILDS_PER_UNIT = 8


class _Lock:
    def __enter__(self):
        t0 = time.time()
        while True:
            try:
                self.fd = os.open(LOCKF, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                if time.time() - t0 > 20:
                    try: os.remove(LOCKF)
                    except OSError: pass
                time.sleep(0.1)

    def __exit__(self, *a):
        os.close(self.fd)
        try: os.remove(LOCKF)
        except OSError: pass


def _load():
    if os.path.exists(REG):
        return json.load(io.open(REG, encoding="utf-8"))
    return {"builds": []}


def _norm(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def units():
    d = os.path.join(LAB, "units")
    return sorted(x for x in os.listdir(d) if os.path.isdir(os.path.join(d, x))) if os.path.isdir(d) else []


def build_path(unit, name):
    return os.path.join(LAB, "units", unit, "builds", name + ".xml")


def register(unit, name, purpose):
    if unit not in units():
        return False, "unknown unit %r" % unit
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_\-]{2,40}$", name):
        return False, "name must be 3-41 characters of letters, digits, '-' or '_'"
    if len((purpose or "").strip()) < 10:
        return False, "say in a sentence what this build is for (--purpose)"
    with _Lock():
        reg = _load()
        mine = [b for b in reg["builds"] if b["unit"] == unit]
        if any(_norm(b["name"]) == _norm(name) for b in reg["builds"]):
            return False, "that name is already taken; pick another"
        if len(mine) >= MAX_BUILDS_PER_UNIT:
            return False, "you already have %d builds registered (limit %d); keep iterating on an existing one" % (len(mine), MAX_BUILDS_PER_UNIT)
        reg["builds"].append({"unit": unit, "name": name, "purpose": purpose.strip(), "ts": int(time.time())})
        os.makedirs(os.path.dirname(REG), exist_ok=True)
        json.dump(reg, io.open(REG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return True, "registered %s (%d of %d). Save it to: %s" % (name, len(mine) + 1, MAX_BUILDS_PER_UNIT, build_path(unit, name))


def registered(unit=None):
    return [b for b in _load()["builds"] if unit is None or b["unit"] == unit]


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("register"); r.add_argument("--unit", required=True); r.add_argument("--name", required=True); r.add_argument("--purpose", required=True)
    l = sub.add_parser("list"); l.add_argument("--unit", required=True)
    p = sub.add_parser("path"); p.add_argument("--unit", required=True); p.add_argument("--name", required=True)
    a = ap.parse_args()
    if a.cmd == "register":
        ok, msg = register(a.unit, a.name, a.purpose)
        print(("OK: " if ok else "REFUSED: ") + msg)
        sys.exit(0 if ok else 1)
    elif a.cmd == "list":
        for b in registered(a.unit):
            print("%s  saved=%s  %s" % (b["name"], os.path.exists(build_path(a.unit, b["name"])), b["purpose"]))
    elif a.cmd == "path":
        if not any(b["name"] == a.name for b in registered(a.unit)):
            print("REFUSED: %r is not registered to unit %s; register it first" % (a.name, a.unit)); sys.exit(1)
        print(build_path(a.unit, a.name))
    else:
        ap.print_help()
