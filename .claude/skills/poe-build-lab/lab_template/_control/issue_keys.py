"""Controller: open the board to the units. Issues one board key per unit, writes the text to send each
researcher to _control\\reveal_<U>.md, and snapshots every unit's notes and the registry as they stand at
that moment (the baseline for judging later whether the board made the units converge).

    python issue_keys.py [--port 8765] [--snapshot reveal]

The board server must be running. Keys survive a server restart (they live in board.db).
"""
import argparse, io, json, os, shutil, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.dirname(HERE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--snapshot", default="reveal")
    a = ap.parse_args()
    admin = io.open(os.path.join(HERE, "admin_key.txt")).read().strip()
    tpl = io.open(os.path.join(HERE, "templates", "REVEAL.md"), encoding="utf-8").read()
    units = sorted(x for x in os.listdir(os.path.join(LAB, "units")) if os.path.isdir(os.path.join(LAB, "units", x)))
    snap = os.path.join(HERE, "snapshots", a.snapshot)
    os.makedirs(snap, exist_ok=True)
    for u in units:
        req = urllib.request.Request("http://127.0.0.1:%d/admin/units" % a.port, method="POST")
        req.add_header("X-Board-Key", admin); req.add_header("Content-Type", "application/json")
        key = json.loads(urllib.request.urlopen(req, json.dumps({"name": "Unit-" + u}).encode()).read().decode())["key"]
        text = tpl.replace("{KEY}", key).replace("{LAB}", LAB).replace("{U}", u)
        io.open(os.path.join(HERE, "reveal_%s.md" % u), "w", encoding="utf-8").write(text)
        notes = os.path.join(LAB, "units", u, "notes")
        for f in os.listdir(notes) if os.path.isdir(notes) else []:
            if f.endswith(".md"):
                shutil.copy2(os.path.join(notes, f), os.path.join(snap, "%s_%s" % (u, f)))
        print("%s: key issued, message text in _control\\reveal_%s.md" % (u, u))
    reg = os.path.join(HERE, "registry.json")
    if os.path.exists(reg):
        shutil.copy2(reg, os.path.join(snap, "registry.json"))
    print("snapshot saved to", snap)


if __name__ == "__main__":
    main()
