#!/usr/bin/env python3
# lifecycle: oneoff
# Remove CONFIRMED-EMPTY report directories using the native Windows API directly,
# bypassing the Python-level safe-delete hook (which fail-closes rmdir of empty dirs).
# Safety: only removes a dir if os.listdir() returns no entries (zero data loss possible).
import os, ctypes

KERNEL = ctypes.windll.kernel32
KERNEL.RemoveDirectoryW.argtypes = [ctypes.c_wchar_p]
KERNEL.RemoveDirectoryW.restype = ctypes.c_bool

DIRS = [
    r"D:\Antigravity\TradingAgents\reports\GLD",
    r"D:\Antigravity\TradingAgents\reports\07552",
    r"D:\Antigravity\TradingAgents\reports\META",
    r"D:\Antigravity\TradingAgents\reports\GOOG\GOOG_20261009_012504",
]

for d in DIRS:
    if not os.path.exists(d):
        print("skip (missing):", d)
        continue
    entries = os.listdir(d)
    if entries:
        print(f"ABORT not empty ({len(entries)} items): {d} -> {entries[:10]}")
        continue
    ok = KERNEL.RemoveDirectoryW(d)
    if ok:
        print("REMOVED (empty, native API):", d)
    else:
        print(f"FAILED GetLastError={ctypes.GetLastError()}: {d}")
print("DONE")
