"""kill-port.py — kill all processes listening on a given port.

Usage: python kill-port.py 8080
"""
import subprocess
import sys

port = sys.argv[1] if len(sys.argv) > 1 else "8080"
result = subprocess.run(["netstat", "-ano"], capture_output=True, text=True)

killed = []
for line in result.stdout.splitlines():
    if f":{port}" in line and "LISTENING" in line:
        pid = line.split()[-1]
        r = subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True)
        if r.returncode == 0:
            killed.append(pid)

if killed:
    print(f"  Killed PIDs: {', '.join(killed)}")
else:
    print(f"  Port {port} was already free.")
