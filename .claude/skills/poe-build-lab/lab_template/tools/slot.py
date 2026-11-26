"""Shared pacing gate for outside services. Several agents work at once, so before each request to a
service that asks for human-paced use, take a slot here; the call blocks until it is your turn.

    python slot.py trade          # before EACH official trade-site request
    python slot.py ninja          # before EACH poe.ninja page load
    python slot.py <any-name> 10  # any other service, with its own minimum gap in seconds

Exit code 0 = go ahead now.
"""
import os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(os.path.dirname(HERE), "_control")
GAP = {"trade": 12.0, "ninja": 8.0}
DEFAULT_GAP = 8.0


def acquire(kind, gap):
    stamp = os.path.join(STATE, "slot_%s.stamp" % kind)
    lock = stamp + ".lock"
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock) > 30:
                    os.remove(lock)
            except OSError:
                pass
            time.sleep(0.2)
            continue
        try:
            last = os.path.getmtime(stamp) if os.path.exists(stamp) else 0
            wait = last + gap - time.time()
            if wait <= 0:
                with open(stamp, "w") as f:
                    f.write(str(time.time()))
                return
        finally:
            os.close(fd)
            os.remove(lock)
        time.sleep(min(max(wait, 0.2), gap))


if __name__ == "__main__":
    if len(sys.argv) < 2 or not re.match(r"^[a-z0-9_\-]{1,30}$", sys.argv[1]):
        print("usage: python slot.py <service-name> [min-gap-seconds]"); sys.exit(2)
    kind = sys.argv[1]
    gap = float(sys.argv[2]) if len(sys.argv) > 2 else GAP.get(kind, DEFAULT_GAP)
    acquire(kind, gap)
    print("go")
