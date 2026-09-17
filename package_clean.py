"""
Build a clean, presentable copy of the project.

Everything excluded is excluded for a stated reason, and the reason is printed,
because "I removed some files" is not a reviewable claim.
"""
import fnmatch
import os
import shutil
import sys

# Derived from where this script sits, so the project folder can be moved or
# renamed without editing anything. `AgenticWarehouse` builds into
# `AgenticWarehouse_Final` beside it.
SRC = os.path.dirname(os.path.abspath(__file__))
DST = os.path.join(os.path.dirname(SRC), os.path.basename(SRC) + "_Final")

# Whole directories that never belong in a delivered copy.
SKIP_DIRS = {
    "node_modules":  "117 MB of downloaded packages; rebuilt by `npm install`",
    "__pycache__":   "compiled Python bytecode, regenerated on first import",
    ".git":          "version-control history",
    ".claude":       "editor/assistant tooling",
    ".vscode":       "editor settings",
    ".idea":         "editor settings",
}

# Filename patterns, with the reason each one goes.
SKIP_GLOBS = [
    ("*.md",          "markdown notes are not part of the delivered system"),
    ("CLAUDE.md",     "assistant tooling instructions"),
    ("*.pyc",         "compiled bytecode"),
    ("*.pyo",         "compiled bytecode"),
    ("*.map",         "source maps expose the unminified source and add ~5.5 MB"),
    (".gitkeep",      "placeholder for an empty directory under version control"),
    (".DS_Store",     "macOS folder metadata"),
    ("Thumbs.db",     "Windows thumbnail cache"),
    ("desktop.ini",   "Windows folder metadata"),
    ("*.log",         "run logs"),
    ("*.tmp",         "temporary file"),
    ("*.bak",         "editor backup"),
    ("*~",            "editor backup"),
    # The build script is not part of what is built.
    ("package_clean.py", "the packaging script itself"),
]

# Exact paths (relative to SRC) that go, with reasons.
SKIP_PATHS = {
    os.path.join("data", "warehouse.backup-before-v2.db"):
        "an old database backup",
    os.path.join("data", "warehouse.db-wal"):
        "SQLite write-ahead journal, folded into the database first",
    os.path.join("data", "warehouse.db-shm"):
        "SQLite shared-memory index, recreated on open",
    os.path.join("data", "cert.pem"):
        "TLS certificate tied to this machine's address; regenerated on --https",
    os.path.join("data", "key.pem"):
        "private key for that certificate; must not be distributed",
    os.path.join("data", "cert.host"):
        "records which address the certificate was issued for on this machine",
}

removed = []
empty = []
copied_files = 0
copied_bytes = 0


def reason_for(rel, name):
    if rel in SKIP_PATHS:
        return SKIP_PATHS[rel]
    for pattern, why in SKIP_GLOBS:
        if fnmatch.fnmatch(name, pattern):
            return why
    return None


if os.path.exists(DST):
    print("Target already exists; removing it so this is a clean build.")
    shutil.rmtree(DST)
os.makedirs(DST)

for root, dirs, files in os.walk(SRC):
    # Prune skipped directories before descending into them.
    for d in list(dirs):
        if d in SKIP_DIRS:
            rel = os.path.relpath(os.path.join(root, d), SRC)
            removed.append((rel + os.sep, SKIP_DIRS[d]))
            dirs.remove(d)

    rel_root = os.path.relpath(root, SRC)
    target_root = DST if rel_root == "." else os.path.join(DST, rel_root)

    for name in files:
        src_path = os.path.join(root, name)
        rel = os.path.relpath(src_path, SRC)

        why = reason_for(rel, name)
        if why:
            removed.append((rel, why))
            continue

        try:
            size = os.path.getsize(src_path)
        except OSError:
            size = 0
        if size == 0:
            empty.append(rel)
            continue

        os.makedirs(target_root, exist_ok=True)
        shutil.copy2(src_path, os.path.join(target_root, name))
        copied_files += 1
        copied_bytes += size

# data/ must exist even though nothing in it may have been copied.
os.makedirs(os.path.join(DST, "data"), exist_ok=True)

print()
print("=" * 72)
print("  COPIED   %d files, %.1f MB" % (copied_files, copied_bytes / 1048576.0))
print("=" * 72)

print("\n  EXCLUDED (%d entries)" % len(removed))
by_reason = {}
for rel, why in removed:
    by_reason.setdefault(why, []).append(rel)
for why in sorted(by_reason):
    items = by_reason[why]
    shown = ", ".join(sorted(items)[:4])
    more = "" if len(items) <= 4 else "  (+%d more)" % (len(items) - 4)
    print("    - %-58s %s%s" % (why, shown, more))

if empty:
    print("\n  EMPTY FILES SKIPPED (%d)" % len(empty))
    for rel in empty:
        print("    - %s" % rel)
else:
    print("\n  EMPTY FILES SKIPPED: none found")

print()
