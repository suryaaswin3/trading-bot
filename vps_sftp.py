#!/usr/bin/env python3
"""Upload a local file to a specified VPS path via SFTP."""
import paramiko, sys

HOST = "168.144.127.242"
USER = "root"
PASS = "ASWIN1TEJREDDY"
LOCAL_PATH = sys.argv[1]
REMOTE_PATH = sys.argv[2]

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    client.connect(HOST, username=USER, password=PASS, timeout=10)
    sftp = client.open_sftp()
    sftp.put(LOCAL_PATH, REMOTE_PATH)
    sftp.close()
    print(f"OK: {REMOTE_PATH}")
finally:
    client.close()