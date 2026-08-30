"""Generate headless_boot.lua from PoB's official HeadlessWrapper.lua.

The wrapper is fetched from GitHub at the tag matching the *installed* PoB
version (read from its manifest.xml), so the boot file always lines up with the
copy it will actually drive. Downloads are cached under cache/.

Two host functions that HeadlessWrapper leaves as stubs get real bodies, and
they are defined where the stubs were -- before dofile("Launch.lua") -- so they
are in place when PoB loads timeless jewel data during OnInit. Patching them
from the host afterwards is too late.

  NewFileSearch()  stub returns nil, so DataJewelFileLoader can never see the
                   .bin cache and always falls through to the compressed path.
  Inflate()        stub returns "", which the loader then writes over the .bin
                   cache -- silently destroying it. We refuse instead of
                   corrupting; pob.py pre-builds every cache with zlib.

Usage:
    python make_boot.py                 # fetch for the installed version
    python make_boot.py path/to/HeadlessWrapper.lua   # use a local copy
"""
import io
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DST = os.path.join(HERE, "headless_boot.lua")
CACHE = os.path.join(HERE, "cache")
RAW = ("https://raw.githubusercontent.com/PathOfBuildingCommunity/"
       "PathOfBuilding/v{version}/src/HeadlessWrapper.lua")

NEW_FILE_SEARCH = '''function NewFileSearch(spec, findDirectories)
	-- [headless] The stub returned nil, which makes DataJewelFileLoader treat
	-- every .bin cache as missing. Report real files instead.
	if type(spec) ~= "string" or spec:find("%*") then
		return nil
	end
	local f = io.open(spec, "rb")
	if not f then
		return nil
	end
	f:close()
	local name = spec:match("([^/\\\\]+)$")
	-- The loader keeps a cache only while the .bin is NEWER than the archive
	-- it came from, and it asks about both through this same function. Lua 5.1
	-- cannot stat, so report the answer that is true by construction: our .bin
	-- caches are always rebuilt from the current archives before boot.
	local mtime = spec:sub(-4) == ".bin" and 2 ^ 40 or 0
	local handle = { }
	function handle:GetFileName() return name end
	function handle:GetFileSize() return 0 end
	function handle:GetFileModifiedTime() return mtime end
	function handle:NextFile() return false end
	return handle
end'''

INFLATE = '''function Inflate(data)
	-- [headless] The stub returned "", and DataJewelFileLoader writes that
	-- straight over the .bin cache -- a silent zero-byte corruption of the
	-- PoB installation. Fail loudly instead.
	--
	-- This cannot be delegated to the Python host: LuaJIT faults when a ctypes
	-- callback returns a value to it. The host works around it instead --
	-- pob.py pre-builds the jewel caches with zlib, and decodes/encodes build
	-- share codes itself (load_build_code / export_code), so PoB never has to.
	error("Inflate() is unavailable headless. Use pob.load_build_code() for "
	      .. "import codes; jewel caches are pre-built by pob.py.", 2)
end'''

DEFLATE = '''function Deflate(data)
	-- [headless] See Inflate above. Build share codes are produced by
	-- pob.export_code(), which compresses build:SaveDB("code") in Python.
	error("Deflate() is unavailable headless. Use pob.export_code().", 2)
end'''


def fetch_wrapper(version):
    """Return HeadlessWrapper.lua for `version`, downloading it once."""
    if not os.path.isdir(CACHE):
        os.makedirs(CACHE)
    cached = os.path.join(CACHE, "HeadlessWrapper.v%s.lua" % version)
    if os.path.exists(cached):
        print("using cached %s" % os.path.basename(cached))
        return io.open(cached, encoding="utf-8").read()

    url = RAW.format(version=version)
    print("fetching %s" % url)
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            text = r.read().decode("utf-8")
    except Exception as exc:
        raise SystemExit(
            "could not fetch the wrapper for PoB v%s (%s).\n"
            "Pass a local HeadlessWrapper.lua path instead." % (version, exc))
    io.open(cached, "w", encoding="utf-8", newline="\n").write(text)
    return text


def replace_block(text, start_marker, end_marker, replacement, label):
    i = text.find(start_marker)
    if i < 0:
        raise SystemExit("anchor not found: %s" % label)
    j = text.find(end_marker, i)
    if j < 0:
        raise SystemExit("end anchor not found: %s" % label)
    return text[:i] + replacement + text[j + len(end_marker):]


def main():
    if len(sys.argv) > 1:
        src = io.open(sys.argv[1], encoding="utf-8").read()
        print("using local %s" % sys.argv[1])
    else:
        # imported here so a local-file run needs no PoB installation
        from pob import install_version
        version = install_version()
        if not version:
            raise SystemExit("could not read the installed PoB version")
        print("installed PoB version: %s" % version)
        src = fetch_wrapper(version)

    src = replace_block(src, "function NewFileSearch()", "end",
                        NEW_FILE_SEARCH, "NewFileSearch")
    src = replace_block(src, "function Deflate(data)", 'return ""\nend',
                        DEFLATE, "Deflate")
    src = replace_block(src, "function Inflate(data)", 'return ""\nend',
                        INFLATE, "Inflate")

    if 'dofile("Launch.lua")' not in src:
        raise SystemExit('expected dofile("Launch.lua") in the wrapper')
    for needle in ("[headless] The stub returned nil",
                   "Inflate() is unavailable", "Deflate() is unavailable"):
        if needle not in src:
            raise SystemExit("patch did not apply: %s" % needle)

    header = ("-- GENERATED by make_boot.py from PoB's HeadlessWrapper.lua.\n"
              "-- Do not edit by hand; re-run make_boot.py after a PoB update.\n")
    # HeadlessWrapper opens with a `#@` marker line, and Lua only skips a
    # leading `#` on line 1 -- so the header has to go after it.
    first, sep, rest = src.partition("\n")
    out = (first + sep + header + rest) if first.startswith("#") else (header + src)

    io.open(DST, "w", encoding="utf-8", newline="\n").write(out)
    print("wrote %s (%d lines)" % (DST, out.count("\n") + 1))


if __name__ == "__main__":
    main()
