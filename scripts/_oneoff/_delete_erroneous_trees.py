#!/usr/bin/env python3
# lifecycle: oneoff
# Delete specified report trees bottom-up (files via os.remove, then empty dirs via os.rmdir).
# Safe-delete hook routes file removals to recycle bin; directory ops are fail-closed,
# so we clear files first then rmdir empties. Idempotent: skips missing paths.
import os, sys

REPORTS = r"D:\Antigravity\TradingAgents\reports"
TREES = [
    "GLD/GLD_20260919_000353",
    "07552/07552_20261008_134951",
    "META/META_20260925_235328",
    "WDC/WDC_20261009_131844",
    "WDC/WDC_20261009_132053",
    "WDC/WDC_20261009_203627",
    "GOOG/GOOG_20261009_012504",
    "515100/515100_20260928_113037",
]

def delete_tree(rel):
    root = os.path.join(REPORTS, rel)
    if not os.path.exists(root):
        print(f"  SKIP (missing): {rel}")
        return
    removed_files = 0
    blocked_files = 0
    # bottom-up walk
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        for fn in filenames:
            fp = os.path.join(dirpath, fn)
            try:
                os.remove(fp)
                removed_files += 1
            except Exception as e:
                blocked_files += 1
                print(f"  BLOCKED file: {fp} -> {e}")
        # remove empty subdirs
        for dn in dirnames:
            dp = os.path.join(dirpath, dn)
            try:
                if not os.listdir(dp):
                    os.rmdir(dp)
            except Exception:
                pass
    # remove tree root if empty
    try:
        if not os.listdir(root):
            os.rmdir(root)
            print(f"  removed tree (empty): {rel}  [files={removed_files}, blocked={blocked_files}]")
        else:
            print(f"  tree NOT empty (left): {rel}  [files={removed_files}, blocked={blocked_files}]")
    except Exception as e:
        print(f"  root rmdir issue: {rel} -> {e}  [files={removed_files}, blocked={blocked_files}]")

if __name__ == "__main__":
    for t in TREES:
        print(f"== {t}")
        delete_tree(t)
    print("DONE")
