"""Controller: create the unit workspaces for a round and stamp each unit's briefs. Python 3.8+.

    python setup_units.py --skills "<project>\\.claude\\skills" [--units A,B,C] [--min-minutes 120] [--max-minutes 180]
                          [--premise PREMISE.md] [--start "YYYY-MM-DD HH:MM"] [--rebrief]

Reads templates\\BRIEF.md and templates\\AUDITOR_BRIEF.md, fills the placeholders, and writes them to
units\\<U>\\BRIEF.md and units\\<U>\\AUDITOR_BRIEF.md. The premise file (written by the controller for this
topic) is pasted into the researcher brief as-is. Run it immediately before launching: the start time is now.
--rebrief only rewrites the two brief files of an existing round (notes and builds are left alone).
"""
import argparse, datetime, io, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.dirname(HERE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--units", default="A,B,C")
    ap.add_argument("--skills", required=True, help="absolute path of the project's skills directory")
    ap.add_argument("--premise", default=os.path.join(HERE, "PREMISE.md"))
    ap.add_argument("--min-minutes", type=int, default=120)
    ap.add_argument("--max-minutes", type=int, default=180)
    ap.add_argument("--max-builds", type=int, default=8)
    ap.add_argument("--start", help='"YYYY-MM-DD HH:MM"; default: now')
    ap.add_argument("--rebrief", action="store_true")
    a = ap.parse_args()

    if not os.path.isfile(a.premise):
        sys.exit("premise file not found: %s (copy templates\\PREMISE.example.md to _control\\PREMISE.md and fill it in)" % a.premise)
    premise = re.sub(r"(?s)<!--.*?-->", "", io.open(a.premise, encoding="utf-8").read()).strip()  # the controller's notes are not pasted
    if not premise:
        sys.exit("the premise file is empty")
    left = re.findall(r"<<[^>]*>>", premise)
    if left:
        sys.exit("the premise still has unfilled placeholders: %s" % ", ".join(sorted(set(left))[:6]))
    if not os.path.isdir(a.skills):
        sys.exit("skills directory not found: %s" % a.skills)

    start = datetime.datetime.strptime(a.start, "%Y-%m-%d %H:%M") if a.start else datetime.datetime.now().replace(second=0, microsecond=0)
    fmt = lambda d: d.strftime("%Y-%m-%d %H:%M")
    values = {
        "LAB": LAB, "SKILLS": os.path.abspath(a.skills), "PREMISE": premise,
        "START": fmt(start),
        "MIN_END": fmt(start + datetime.timedelta(minutes=a.min_minutes)),
        "MAX_END": fmt(start + datetime.timedelta(minutes=a.max_minutes)),
        "WRAP_UP": fmt(start + datetime.timedelta(minutes=a.max_minutes - 20)),
        "MIN_MINUTES": str(a.min_minutes), "MAX_MINUTES": str(a.max_minutes), "MAX_BUILDS": str(a.max_builds),
    }
    units = [u.strip() for u in a.units.split(",") if u.strip()]
    for u in units:
        base = os.path.join(LAB, "units", u)
        if os.path.isdir(base) and not a.rebrief and any(os.listdir(os.path.join(base, d)) for d in ("notes", "builds", "docs") if os.path.isdir(os.path.join(base, d))):
            sys.exit("units\\%s already has work in it. Archive the previous round first (archive_round.py), or pass --rebrief." % u)
    for u in units:
        base = os.path.join(LAB, "units", u)
        for d in ("notes", os.path.join("notes", "raw"), "builds", "auditor_tmp", "docs"):
            os.makedirs(os.path.join(base, d), exist_ok=True)
        for name in ("BRIEF.md", "AUDITOR_BRIEF.md"):
            t = io.open(os.path.join(HERE, "templates", name), encoding="utf-8").read()
            for k, v in dict(values, U=u).items():
                t = t.replace("{%s}" % k, v)
            stray = sorted(set(re.findall(r"\{[A-Z_]{2,}\}", t)))
            if stray:
                sys.exit("template %s has unknown placeholders: %s" % (name, stray))
            io.open(os.path.join(base, name), "w", encoding="utf-8").write(t)
    os.makedirs(os.path.join(LAB, "shared"), exist_ok=True)
    if not a.rebrief:
        io.open(os.path.join(HERE, "start_time.txt"), "w", encoding="utf-8").write(values["START"])
        io.open(os.path.join(HERE, "start_epoch.txt"), "w", encoding="utf-8").write(str(int(start.timestamp())))
        reg = os.path.join(HERE, "registry.json")
        mb = os.path.join(LAB, "tools", "registry.py")
        s = io.open(mb, encoding="utf-8").read()
        s2 = re.sub(r"MAX_BUILDS_PER_UNIT = \d+", "MAX_BUILDS_PER_UNIT = %d" % a.max_builds, s)
        if s2 != s:
            io.open(mb, "w", encoding="utf-8").write(s2)
    print("units ready: %s" % ", ".join(units))
    print("start %s | earliest finish %s | wrap up from %s | hard stop %s" % (values["START"], values["MIN_END"], values["WRAP_UP"], values["MAX_END"]))


if __name__ == "__main__":
    main()
