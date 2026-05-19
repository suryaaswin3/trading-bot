#!/usr/bin/env python3
"""SSH helper for VPS testing - uses paramiko for password-based auth."""

import paramiko
import sys
import json
import os

HOST = "168.144.127.242"
USER = "root"
PASS = "ASWIN1TEJREDDY"

def run(cmd, timeout=15):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(HOST, username=USER, password=PASS, timeout=10)
        stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode('utf-8', errors='replace')
        err = stderr.read().decode('utf-8', errors='replace')
        return {"exit": exit_code, "stdout": out, "stderr": err}
    except Exception as e:
        return {"exit": -1, "stdout": "", "stderr": str(e)}
    finally:
        client.close()

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "hostname && date"
    timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    result = run(cmd, timeout)
    print(json.dumps(result))