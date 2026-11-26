"""Controller: add up what a round cost, from the agent transcripts of this Claude Code session.

    python token_usage.py "<...\\.claude\\projects\\<project>\\<session-id>\\subagents>" [--since "YYYY-MM-DD HH:MM"]

An agent is counted when its first message names this lab's folder. It is a researcher when that message
points at units\\<U>\\BRIEF.md and an auditor when it points at AUDITOR_BRIEF.md. --since drops agents that
started before the given local time (use the round's start time when the lab has hosted earlier rounds).

Columns: requests; "new" = tokens written into context for the first time (uncached input + cache writes);
"re-read" = cache reads, i.e. the whole conversation sent again on every tool call — this is what grows with
the length of an agent's run; "out" = tokens the model produced.
"""
import collections, datetime, glob, io, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__)); LAB = os.path.dirname(HERE)


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    folder = sys.argv[1]
    since = None
    if "--since" in sys.argv:
        since = datetime.datetime.strptime(sys.argv[sys.argv.index("--since") + 1], "%Y-%m-%d %H:%M").astimezone()
    lab_key = os.path.basename(LAB)
    rows = collections.defaultdict(collections.Counter); peak = {}
    for f in glob.glob(os.path.join(folder, "agent-*.jsonl")):
        first = None; t0 = None; seen = set(); u = collections.Counter(); top = 0; compactions = 0
        for line in io.open(f, encoding="utf-8", errors="replace"):
            try: d = json.loads(line)
            except ValueError: continue
            if t0 is None and d.get("timestamp"):
                t0 = datetime.datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).astimezone()
            if d.get("subtype") == "compact_boundary":
                compactions += 1
            m = d.get("message") or {}
            if first is None and m.get("role") == "user":
                c = m.get("content"); first = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
            us = m.get("usage")
            if us and m.get("role") == "assistant" and m.get("id") not in seen:
                seen.add(m.get("id"))
                new = (us.get("input_tokens") or 0) + (us.get("cache_creation_input_tokens") or 0)
                reread = us.get("cache_read_input_tokens") or 0
                u["requests"] += 1; u["new"] += new; u["reread"] += reread; u["out"] += us.get("output_tokens") or 0
                top = max(top, new + reread)
        if not first or lab_key not in first or (since and t0 and t0 < since):
            continue
        unit = re.search(r"units[\\/]+([A-Za-z0-9_-]+)[\\/]+(AUDITOR_)?BRIEF\.md", first.replace("\\\\", "\\"))
        if not unit:
            continue
        key = ("auditor " if unit.group(2) else "researcher ") + unit.group(1)
        rows[key].update(u); rows[key]["agents"] += 1; rows[key]["compactions"] += compactions
        peak[key] = max(peak.get(key, 0), top)
    if not rows:
        sys.exit("no agents of this lab found in %s" % folder)
    M = 1e6
    total = collections.Counter()
    print("%-16s %6s %8s %9s %10s %8s %12s %s" % ("who", "agents", "requests", "new (M)", "re-read(M)", "out (M)", "peak context", "compactions"))
    for key in sorted(rows):
        r = rows[key]; total.update(r)
        print("%-16s %6d %8d %9.2f %10.1f %8.2f %12d %d" % (key, r["agents"], r["requests"], r["new"] / M, r["reread"] / M, r["out"] / M, peak[key], r["compactions"]))
    print("%-16s %6d %8d %9.2f %10.1f %8.2f   total processed %.1f M" % ("ALL", total["agents"], total["requests"], total["new"] / M, total["reread"] / M, total["out"] / M, (total["new"] + total["reread"] + total["out"]) / M))


if __name__ == "__main__":
    main()
