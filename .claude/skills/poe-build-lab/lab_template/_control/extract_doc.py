"""Controller: recover a unit's deliverable document from its agent transcript.

Use only when a researcher reports that its file-writing tool refused to write docs\\build_info.md and it
put the full text in its final message instead (after a line reading "=== build_info.md 全文 ===").

    python extract_doc.py <U> "<...\\subagents\\agent-<id>.jsonl>" ["marker text"]

Writes units\\<U>\\docs\\build_info.md with the text exactly as the researcher wrote it.
"""
import io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__)); LAB = os.path.dirname(HERE)


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    unit, path = sys.argv[1], sys.argv[2]
    marker = sys.argv[3] if len(sys.argv) > 3 else "=== build_info.md 全文 ==="
    best = [None]

    def walk(o):
        if isinstance(o, str):
            if marker in o and (best[0] is None or len(o) >= len(best[0])):
                best[0] = o
        elif isinstance(o, dict):
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)

    for line in io.open(path, encoding="utf-8", errors="replace"):
        line = line.strip()
        if line:
            try: walk(json.loads(line))
            except ValueError: pass
    if not best[0]:
        sys.exit("marker %r not found in %s" % (marker, path))
    body = best[0][best[0].rindex(marker):]
    body = body[body.index("\n"):].lstrip("\n") if "\n" in body else ""
    out = os.path.join(LAB, "units", unit, "docs", "build_info.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    io.open(out, "w", encoding="utf-8").write(body.rstrip() + "\n")
    print("wrote %s (%d characters)" % (out, len(body)))


if __name__ == "__main__":
    main()
