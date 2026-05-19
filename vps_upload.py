#!/usr/bin/env python3
"""Upload a local file to the VPS via paramiko SFTP."""
import paramiko, sys, os

HOST = "168.144.127.242"
USER = "root"
PASS = "ASWIN1TEJREDDY"
REMOTE_PATH = "/opt/trading-bot/test_paper_flow.py"
LOCAL_PATH = sys.argv[1]

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    client.connect(HOST, username=USER, password=PASS, timeout=10)
    sftp = client.open_sftp()
    sftp.put(LOCAL_PATH, REMOTE_PATH)
    sftp.close()
    print(f"Uploaded {LOCAL_PATH} to {REMOTE_PATH}")
finally:
    client.close()