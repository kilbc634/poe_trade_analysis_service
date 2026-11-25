"""PoB slots: long-lived headless PoB engines you talk to from short commands.

A slot is one PoB process that stays up between commands, so only the first
command pays the ~13 s boot. Several slots can run side by side; each has an
auto-generated id and an optional name, so concurrent agents do not step on
each other.

A slot that sits idle for 10 minutes (or grows past the memory cap) hibernates:
it writes the build's share code to .pob-operator/<id>-<timestamp>.code and
exits, giving all its memory back. The next command for that slot boots a fresh
engine and restores the snapshot (one more ~13 s wait).

    python slot.py list
    python slot.py new --name flicker --load "C:\\...\\Builds\\x.xml"
    python slot.py -s flicker eval "return tostring(build.calcsTab.mainOutput.Dex)"
    python slot.py -s flicker eval --file change.lua
    python slot.py -s flicker load other.xml        (xml file or share-code file)
    python slot.py -s flicker recalc | export | snapshot | sleep | close

From a script:  from slot import Slot;  p = Slot("flicker")  -- then p.eval(),
p.load_build(), p.load_build_code(), p.recalc(), p.export_code() as with PoB().

State lives in .pob-operator/ next to this file (not the cwd), so every agent
on the machine sees the same slot list.
"""
import argparse
import ctypes
import datetime
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, ".pob-operator")
SLOTS = os.path.join(STATE, "slots")
LOGS = os.path.join(STATE, "logs")

IDLE_SEC = float(os.environ.get("POB_SLOT_IDLE_SEC", "600"))
MEM_CAP_MB = float(os.environ.get("POB_SLOT_MEM_MB", "800"))
KEEP_SNAPSHOTS = 20
BOOT_TIMEOUT = 120
DIGEST_KEYS = ("TotalDPS", "CombinedDPS", "FullDPS", "Life", "Mana", "EnergyShield",
               "TotalEHP", "Str", "Dex", "Int")


class SlotError(RuntimeError):
    pass


# ---------------------------------------------------------------- small helpers

def _mkdirs():
    for d in (STATE, SLOTS, LOGS):
        os.makedirs(d, exist_ok=True)


def _stamp():
    now = datetime.datetime.utcnow()
    return now.strftime("%Y-%m-%dT%H-%M-%S-") + "%03dZ" % (now.microsecond // 1000)


def _rec_path(slot_id):
    return os.path.join(SLOTS, slot_id + ".json")


def _read_rec(slot_id):
    try:
        with open(_rec_path(slot_id), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _write_rec(rec):
    path = _rec_path(rec["id"])
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=1)
    for _ in range(20):                      # Windows: a reader may hold it briefly
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05)
    os.replace(tmp, path)


def _all_recs():
    _mkdirs()
    out = []
    for name in sorted(os.listdir(SLOTS)):
        if name.endswith(".json"):
            rec = _read_rec(name[:-5])
            if rec:
                out.append(rec)
    return out


def _pid_alive(pid):
    if not pid:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = ctypes.c_void_p
    h = k.OpenProcess(0x1000, False, int(pid))    # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = ctypes.c_ulong()
    k.GetExitCodeProcess(ctypes.c_void_p(h), ctypes.byref(code))
    k.CloseHandle(ctypes.c_void_p(h))
    return code.value == 259                      # STILL_ACTIVE


def _mem_mb():
    """Private bytes of this process, in MB (0 if it cannot be read)."""
    if os.name != "nt":
        return 0
    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (n, ctypes.c_size_t) for n in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage",
                "PrivateUsage")]
    k = ctypes.WinDLL("kernel32")
    k.GetCurrentProcess.restype = wintypes.HANDLE
    ps = ctypes.WinDLL("psapi")
    ps.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    m = PMC()
    m.cb = ctypes.sizeof(m)
    if not ps.GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(m), m.cb):
        return 0
    return m.PrivateUsage >> 20


def lua_quote(text):
    """A Lua long-bracket literal holding text verbatim."""
    eq = "="
    while "]" + eq + "]" in text or text.endswith("]" + eq):
        eq += "="
    return "[%s[\n%s]%s]" % (eq, text, eq)


def _parse_digest(text):
    out = {}
    for line in (text or "").splitlines():
        k, _, v = line.partition("=")
        if k:
            out[k] = v
    return out


def _digest_diff(before, after):
    diffs = []
    for k, a in before.items():
        b = after.get(k)
        if a == b:
            continue
        try:
            fa, fb = float(a), float(b)
            if abs(fa - fb) <= 1e-6 * max(1.0, abs(fa)):
                continue
        except (TypeError, ValueError):
            pass
        diffs.append("%s: %s -> %s" % (k, a, b))
    return diffs


# ----------------------------------------------------------------------- server

DIGEST_LUA = (
    "local o = build and build.calcsTab and build.calcsTab.mainOutput\n"
    "if not o then return '' end\n"
    "local t = {}\n"
    "for _, k in ipairs({%s}) do t[#t+1] = k .. '=' .. tostring(o[k]) end\n"
    "local env = build.calcsTab.mainEnv\n"
    "local sk = env and env.player and env.player.mainSkill\n"
    "local ge = sk and sk.activeEffect and sk.activeEffect.grantedEffect\n"
    "t[#t+1] = 'mainSkill=' .. tostring(ge and ge.name)\n"
    "return table.concat(t, '\\n')" % ", ".join('"%s"' % k for k in DIGEST_KEYS))


class _Server:
    def __init__(self, slot_id):
        self.id = slot_id
        self.rec = _read_rec(slot_id) or {"id": slot_id}
        self.pob = None
        self.stop = None            # None | "sleep" | "close"

    def log(self, msg):
        print("[%s] %s" % (_stamp(), msg), file=sys.stderr, flush=True)

    def save(self, **kw):
        self.rec.update(kw)
        _write_rec(self.rec)

    def digest(self):
        try:
            return _parse_digest(self.pob.eval(DIGEST_LUA))
        except Exception as exc:                       # noqa: BLE001
            self.log("digest failed: %s" % exc)
            return {}

    def write_snapshot(self, reason):
        """Share code of the build as it stands -> .pob-operator/<id>-<ts>.code"""
        try:
            code = self.pob.export_code()
        except Exception as exc:                       # noqa: BLE001
            self.log("snapshot failed (%s): %s" % (reason, exc))
            return None
        path = os.path.join(STATE, "%s-%s.code" % (self.id, _stamp()))
        with open(path, "w", encoding="ascii") as fh:
            fh.write(code)
        self.save(snapshot=path, snapshot_at=time.time(), snapshot_reason=reason,
                  digest=self.digest())
        mine = sorted(f for f in os.listdir(STATE)
                      if f.startswith(self.id + "-") and f.endswith(".code"))
        for old in mine[:-KEEP_SNAPSHOTS]:
            try:
                os.remove(os.path.join(STATE, old))
            except OSError:
                pass
        self.log("snapshot (%s): %s" % (reason, path))
        return path

    def restore(self):
        path = self.rec.get("snapshot")
        if not path or not os.path.isfile(path):
            return
        before = self.rec.get("digest") or {}
        with open(path, encoding="ascii") as fh:
            self.pob.load_build_code(fh.read())
        diffs = _digest_diff(before, self.digest()) if before else []
        self.save(restored_from=path, restore_diffs=diffs)
        self.log("restored %s (%s)" % (path, "identical" if not diffs else "; ".join(diffs)))

    # ---- requests

    def handle(self, req):
        op, p = req.get("op"), self.pob
        if op == "ping":
            return "pong"
        if op == "eval":
            return p.eval(req["code"])
        if op == "load":
            path = req["path"]
            with open(path, encoding="utf-8", errors="replace") as fh:
                head = fh.read(200)
            if head.lstrip().startswith("<"):
                p.load_build(path)
            else:
                with open(path, encoding="utf-8") as fh:
                    p.load_build_code(fh.read())
            self.rec["build"] = path
            self.rec["loads"] = self.rec.get("loads", 0) + 1
            return "loaded " + path
        if op == "load_code":
            p.load_build_code(req["code"])
            self.rec["build"] = req.get("label") or "(share code)"
            self.rec["loads"] = self.rec.get("loads", 0) + 1
            return "loaded share code"
        if op == "recalc":
            p.recalc()
            return "recalculated"
        if op == "export":
            return p.export_code()
        if op == "snapshot":
            return self.write_snapshot("manual")
        if op in ("sleep", "close"):
            self.stop = op
            return op
        raise SlotError("unknown op %r" % op)

    def serve_one(self, conn):
        conn.settimeout(30)
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = conn.recv(1 << 16)
            if not chunk:
                break
            buf += chunk
        try:
            req = json.loads(buf.decode("utf-8"))
            if req.get("token") != self.rec["token"]:
                raise SlotError("bad token")
            resp = {"ok": True, "result": self.handle(req)}
        except Exception as exc:                       # noqa: BLE001
            resp = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
        conn.settimeout(None)
        conn.sendall(json.dumps(resp).encode("utf-8") + b"\n")

    def hibernate(self, reason):
        self.write_snapshot(reason)
        self.save(state="hibernated", pid=None, port=None, hibernated_at=time.time(),
                  hibernate_reason=reason)
        self.log("hibernated (%s)" % reason)

    def run(self):
        from pob import PoB                            # import here: chdir()s on boot
        t0 = time.time()
        self.save(state="starting", pid=os.getpid(), port=None)
        self.pob = PoB()
        self.restore()
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(8)
        srv.settimeout(2.0)
        now = time.time()
        self.save(state="running", port=srv.getsockname()[1], started_at=now,
                  last_used=now, boot_sec=round(now - t0, 1), mem_mb=_mem_mb(),
                  hibernate_reason=None)
        self.log("running on port %d after %.1fs" % (self.rec["port"], now - t0))
        last = now
        while True:
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                if time.time() - last > IDLE_SEC:
                    srv.close()
                    self.hibernate("idle")
                    return
                continue
            try:
                self.serve_one(conn)
            except Exception as exc:                   # noqa: BLE001
                self.log("request failed: %s" % exc)
            finally:
                conn.close()
            last = time.time()
            mem = _mem_mb()
            if self.stop == "close":
                srv.close()
                self.write_snapshot("close")
                try:
                    os.remove(_rec_path(self.id))
                except OSError:
                    pass
                self.log("closed")
                return
            if self.stop == "sleep" or (MEM_CAP_MB and mem > MEM_CAP_MB):
                srv.close()
                self.hibernate("manual" if self.stop == "sleep" else "memory %dMB" % mem)
                return
            self.save(last_used=last, mem_mb=mem)


# ----------------------------------------------------------------------- client

def _spawn(slot_id):
    _mkdirs()
    log = open(os.path.join(LOGS, slot_id + ".log"), "ab")
    cmd = [sys.executable, os.path.abspath(__file__), "_serve", slot_id]
    kw = dict(stdin=subprocess.DEVNULL, stdout=log, stderr=log, cwd=HERE, close_fds=True)
    if os.name == "nt":
        base = 0x00000008 | 0x00000200             # DETACHED_PROCESS | NEW_PROCESS_GROUP
        try:
            # outlive the shell / agent tool call that happened to start it
            subprocess.Popen(cmd, creationflags=base | 0x01000000, **kw)   # BREAKAWAY_FROM_JOB
        except OSError:
            subprocess.Popen(cmd, creationflags=base, **kw)
    else:
        subprocess.Popen(cmd, start_new_session=True, **kw)
    log.close()


def _refresh(rec):
    """Notice an engine that died without hibernating (crash, reboot, kill)."""
    if rec.get("state") in ("running", "starting") and not _pid_alive(rec.get("pid")):
        rec.update(state="hibernated", pid=None, port=None,
                   hibernate_reason="engine died; changes after the last snapshot are lost")
        _write_rec(rec)
    return rec


def resolve(sel):
    recs = [_refresh(r) for r in _all_recs()]
    hits = [r for r in recs if r["id"] == sel] or [r for r in recs if r.get("name") == sel]
    if not hits:
        known = ", ".join("%s%s" % (r["id"], " (%s)" % r["name"] if r.get("name") else "")
                          for r in recs) or "none"
        raise SlotError("no slot %r. Existing slots: %s. Create one with: slot.py new" % (sel, known))
    return hits[0]


def _wake(rec, quiet=False):
    """Make sure the slot's engine is up; returns the fresh record."""
    slot_id = rec["id"]
    lock = _rec_path(slot_id)[:-5] + ".lock"
    rec = _refresh(_read_rec(slot_id) or rec)
    if rec.get("state") == "running":
        return rec
    t0 = time.time()
    if rec.get("state") != "starting":
        try:
            if os.path.exists(lock) and time.time() - os.path.getmtime(lock) > BOOT_TIMEOUT:
                os.remove(lock)
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            mine = True
        except OSError:
            mine = False                               # someone else is waking it
        if mine:
            if not quiet:
                why = rec.get("hibernate_reason")
                print("slot %s is %s -- booting PoB (about 13s)..." % (
                    slot_id, "hibernated (%s)" % why if why else "new"), file=sys.stderr)
            rec.update(state="starting", pid=None)
            _write_rec(rec)
            _spawn(slot_id)
    try:
        while time.time() - t0 < BOOT_TIMEOUT:
            time.sleep(0.3)
            cur = _read_rec(slot_id)
            if cur and cur.get("state") == "running":
                if not quiet and cur.get("restored_from") and cur.get("started_at", 0) >= t0 - 1:
                    diffs = cur.get("restore_diffs") or []
                    print("restored %s%s" % (
                        os.path.basename(cur["restored_from"]),
                        "" if not diffs else
                        "  WARNING numbers differ from before hibernation: " + "; ".join(diffs)),
                        file=sys.stderr)
                return cur
            if cur and cur.get("state") == "starting" and cur.get("pid") \
                    and not _pid_alive(cur["pid"]):
                break
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass
    raise SlotError("slot %s did not come up; see %s" % (
        slot_id, os.path.join(LOGS, slot_id + ".log")))


def call(sel, op, timeout=600, **params):
    rec = resolve(sel)
    for attempt in (1, 2, 3):
        rec = _wake(rec)
        try:
            conn = socket.create_connection(("127.0.0.1", rec["port"]), timeout=5)
        except OSError:
            time.sleep(0.5)                            # went to sleep under us; wake again
            rec = _read_rec(rec["id"]) or rec
            continue
        with conn:
            conn.settimeout(timeout)
            req = dict(params, op=op, token=rec["token"])
            conn.sendall(json.dumps(req).encode("utf-8") + b"\n")
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = conn.recv(1 << 16)
                if not chunk:
                    break
                buf += chunk
        if not buf:
            raise SlotError("slot %s closed the connection without answering" % rec["id"])
        resp = json.loads(buf.decode("utf-8"))
        if not resp.get("ok"):
            raise SlotError(resp.get("error") or "request failed")
        return resp.get("result")
    raise SlotError("could not reach slot %s" % rec["id"])


def new_slot(name=None):
    _mkdirs()
    recs = _all_recs()
    if name:
        if not re.match(r"^[A-Za-z0-9_.-]{1,40}$", name):
            raise SlotError("name must be 1-40 chars of letters, digits, _ . -")
        if any(r.get("name") == name or r["id"] == name for r in recs):
            raise SlotError("a slot named %r already exists (slot.py list)" % name)
    taken = {r["id"] for r in recs}
    while True:
        slot_id = "pob-" + secrets.token_hex(2)
        if slot_id not in taken:
            break
    rec = {"id": slot_id, "name": name, "token": secrets.token_hex(16), "state": "hibernated",
           "hibernate_reason": None, "created": time.time(), "loads": 0}
    _write_rec(rec)
    _wake(rec)
    return slot_id


class Slot:
    """Drop-in for pob.PoB() that talks to a slot instead of booting an engine."""

    def __init__(self, sel=None):
        sel = sel or os.environ.get("POB_SLOT")
        if not sel:
            raise SlotError("which slot? pass an id/name or set POB_SLOT (slot.py list)")
        self.id = resolve(sel)["id"]

    @classmethod
    def new(cls, name=None):
        return cls(new_slot(name))

    def eval(self, chunk):
        return call(self.id, "eval", code=chunk)

    def load_build(self, path):
        return call(self.id, "load", path=os.path.abspath(path))

    def load_build_code(self, code, label=None):
        return call(self.id, "load_code", code=code, label=label)

    def recalc(self):
        return call(self.id, "recalc")

    def export_code(self):
        return call(self.id, "export")

    def close(self):                                   # PoB() compatibility: keeps the slot
        pass


# -------------------------------------------------------------------------- CLI

def _ago(ts):
    if not ts:
        return "-"
    s = int(time.time() - ts)
    return "%ds" % s if s < 90 else "%dm" % (s // 60) if s < 5400 else "%dh" % (s // 3600)


def _list():
    recs = [_refresh(r) for r in _all_recs()]
    if not recs:
        print("no slots. Create one with: python slot.py new [--name NAME] [--load FILE]")
        return
    rows = [("ID", "NAME", "STATE", "IDLE", "MEM", "LOADS", "BUILD")]
    for r in recs:
        running = r.get("state") == "running"
        state = r.get("state", "?")
        if state == "hibernated" and r.get("hibernate_reason"):
            state += " (%s)" % r["hibernate_reason"]
        rows.append((r["id"], r.get("name") or "-", state,
                     _ago(r.get("last_used")) if running else "-",
                     "%dMB" % r["mem_mb"] if running and r.get("mem_mb") else "-",
                     str(r.get("loads", 0)),
                     os.path.basename(r.get("build") or "") or "-"))
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        print("  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip())
    for r in recs:
        if r.get("state") == "hibernated" and r.get("snapshot"):
            print("%s snapshot: %s" % (r["id"], r["snapshot"]))


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["_serve"]:
        _Server(argv[1]).run()
        return 0

    ap = argparse.ArgumentParser(prog="slot.py", description="Long-lived headless PoB slots.")
    ap.add_argument("-s", "--slot", default=os.environ.get("POB_SLOT"),
                    help="slot id or name (or set POB_SLOT)")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("list", help="every slot: running or hibernated, memory, loaded build")
    p = sub.add_parser("new", help="start a new slot and print its id")
    p.add_argument("--name")
    p.add_argument("--load", help="build .xml or share-code file to load right away")
    p = sub.add_parser("load", help="load a build .xml or a share-code file")
    p.add_argument("path")
    p = sub.add_parser("eval", help="run a Lua chunk; prints what it returns")
    p.add_argument("code", nargs="?")
    p.add_argument("--file", help="read the Lua chunk from a file ('-' for stdin)")
    sub.add_parser("recalc", help="recalculate after changes made with eval")
    p = sub.add_parser("export", help="print (or --out) the build's share code")
    p.add_argument("--out")
    sub.add_parser("snapshot", help="write a share-code snapshot now and print its path")
    sub.add_parser("sleep", help="hibernate now: snapshot, exit, free the memory")
    sub.add_parser("close", help="snapshot, stop the engine and remove the slot")
    args = ap.parse_args(argv)

    try:
        if args.cmd in (None, "list"):
            _list()
            return 0
        if args.cmd == "new":
            slot_id = new_slot(args.name)
            if args.load:
                call(slot_id, "load", path=os.path.abspath(args.load))
            print(slot_id)
            return 0
        if not args.slot:
            raise SlotError("which slot? use -s ID_OR_NAME (python slot.py list)")
        sel = args.slot
        if args.cmd == "load":
            print(call(sel, "load", path=os.path.abspath(args.path)))
        elif args.cmd == "eval":
            if args.file == "-":
                code = sys.stdin.read()
            elif args.file:
                with open(args.file, encoding="utf-8") as fh:
                    code = fh.read()
            elif args.code is not None:
                code = args.code
            else:
                raise SlotError("eval needs a Lua chunk or --file")
            out = call(sel, "eval", code=code)
            if out is not None:
                print(out)
        elif args.cmd == "recalc":
            print(call(sel, "recalc"))
        elif args.cmd == "export":
            code = call(sel, "export")
            if args.out:
                with open(args.out, "w", encoding="ascii") as fh:
                    fh.write(code)
                print("wrote " + os.path.abspath(args.out))
            else:
                print(code)
        elif args.cmd == "snapshot":
            print(call(sel, "snapshot"))
        elif args.cmd == "sleep":
            rec = resolve(sel)
            if _refresh(rec).get("state") != "running":
                print("%s is already hibernated" % rec["id"])
            else:
                call(sel, "sleep")
                print("%s hibernating" % rec["id"])
        elif args.cmd == "close":
            rec = _refresh(resolve(sel))
            if rec.get("state") == "running":
                call(sel, "close")
            else:
                os.remove(_rec_path(rec["id"]))
            print("%s closed (snapshots stay in %s)" % (rec["id"], STATE))
        return 0
    except SlotError as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
