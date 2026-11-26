"""Controller: put the finished round away so the next round starts from empty workspaces.

    python archive_round.py            # moves the round into round<N>\\ (N = next free number)

Moves units\\, board\\board.db and this round's control state (registry, snapshots, reveal texts, start
stamps, the premise) into round<N>\\. Stop the board server first (it holds board.db open). A unit folder
that another program has open cannot be moved; it is copied, verified and then emptied instead.
The next round's researchers are told not to read anything outside their own unit, tools\\ and shared\\ —
the archive stays inside the lab, so that rule is the only thing keeping old rounds private. Move round<N>\\
somewhere else afterwards if stronger isolation is wanted.
"""
import filecmp, os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__)); LAB = os.path.dirname(HERE)


def same_tree(a, b):
    c = filecmp.dircmp(a, b)
    if c.left_only or c.right_only or c.diff_files or c.funny_files:
        return False
    return all(same_tree(os.path.join(a, d), os.path.join(b, d)) for d in c.common_dirs)


def move(src, dst):
    if not os.path.exists(src):
        return
    try:
        shutil.move(src, dst)
        return
    except (PermissionError, OSError):
        pass
    if os.path.isdir(src):
        shutil.copytree(src, dst)
        if not same_tree(src, dst):
            sys.exit("copy of %s did not verify; nothing was deleted" % src)
        for name in os.listdir(src):
            p = os.path.join(src, name)
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        print("  (%s was locked by another program: copied, verified, then emptied)" % src)
    else:
        sys.exit("cannot move %s — is the board server still running?" % src)


def main():
    n = 1
    while os.path.exists(os.path.join(LAB, "round%d" % n)):
        n += 1
    dst = os.path.join(LAB, "round%d" % n)
    os.makedirs(os.path.join(dst, "units"))
    units_dir = os.path.join(LAB, "units")
    for u in sorted(os.listdir(units_dir)) if os.path.isdir(units_dir) else []:
        move(os.path.join(units_dir, u), os.path.join(dst, "units", u))
    move(os.path.join(LAB, "board", "board.db"), os.path.join(dst, "board.db"))
    for f in os.listdir(HERE):
        if f in ("registry.json", "snapshots", "start_time.txt", "start_epoch.txt", "PREMISE.md") or f.startswith("reveal_") or (f.startswith("slot_") and f.endswith(".stamp")):
            if f.startswith("slot_"):
                os.remove(os.path.join(HERE, f))
            else:
                move(os.path.join(HERE, f), os.path.join(dst, f))
    for u in os.listdir(units_dir) if os.path.isdir(units_dir) else []:
        p = os.path.join(units_dir, u)
        if os.path.isdir(p) and not os.listdir(p):
            try: os.rmdir(p)
            except OSError: pass
    print("round archived to", dst)


if __name__ == "__main__":
    main()
