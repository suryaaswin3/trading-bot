"""Deploy trading bot to VPS via SSH with password auth.

Transfers files, installs dependencies, sets up cron and timezone.
Run from the project root directory.

Usage:
    uv run python deploy.py
"""

from __future__ import annotations

import os
import sys
import time

VPS_HOST = "168.144.127.242"
VPS_USER = "root"
# VPS_PASSWORD must be set as environment variable (not hardcoded!)
VPS_PATH = "/opt/trading-bot"

FILES = [
    "pyproject.toml",
    "uv.lock",
    ".gitignore",
    "generate_token.py",
    "start_bot.py",
    "credentials.env",
    ".env",
    "requirements-token.txt",
    "deploy.sh",
    "trading_bot",  # directory — handled recursively
    "ops_api",  # ops API layer
    "dashboard",  # Streamlit dashboard
    "systemd",  # systemd service unit files
]


def sftp_put_dir(sftp, local_dir: str, remote_dir: str) -> None:
    """Recursively upload a directory via SFTP."""
    for entry in os.listdir(local_dir):
        local_path = os.path.join(local_dir, entry).replace("\\", "/")
        remote_path = f"{remote_dir}/{entry}"
        if os.path.isdir(local_path):
            try:
                sftp.stat(remote_path)
            except FileNotFoundError:
                sftp.mkdir(remote_path)
            sftp_put_dir(sftp, local_path, remote_path)
        else:
            sftp.put(local_path, remote_path)


def main() -> None:
    import paramiko

    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)

    vps_pass = os.environ.get("VPS_PASSWORD", "")
    if not vps_pass:
        print("ERROR: VPS_PASSWORD environment variable not set")
        print("Set it before running: export VPS_PASSWORD='your-password'")
        sys.exit(1)

    print(f"=== Deploying trading bot to {VPS_USER}@{VPS_HOST} ===")

    # ── Connect via SSH ────────────────────────────────────────────────
    print("[1/5] Connecting to VPS...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(
            VPS_HOST,
            username=VPS_USER,
            password=vps_pass,
            look_for_keys=False,
            allow_agent=False,
            timeout=30,
        )
    except paramiko.AuthenticationException:
        print("ERROR: Authentication failed. Check password.")
        sys.exit(1)
    except paramiko.SSHException as e:
        print(f"ERROR: SSH connection failed: {e}")
        sys.exit(1)
    except OSError as e:
        print(f"ERROR: Cannot reach {VPS_HOST}: {e}")
        sys.exit(1)

    print(f"  Connected to {VPS_HOST}")

    def run(cmd: str, timeout: int = 60) -> tuple[int, str, str]:
        _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        return exit_code, stdout.read().decode(), stderr.read().decode()

    # ── Create remote directory ────────────────────────────────────────
    print("[2/5] Creating remote directory...")
    run(f"mkdir -p {VPS_PATH}")

    # ── Upload files via SFTP ──────────────────────────────────────────
    print("[3/5] Uploading project files...")
    sftp = ssh.open_sftp()

    try:
        for item in FILES:
            local_path = os.path.join(base_dir, item).replace("\\", "/")
            remote_path = f"{VPS_PATH}/{item}"

            if not os.path.exists(local_path):
                print(f"  SKIP (not found): {item}")
                continue

            if os.path.isdir(local_path):
                try:
                    sftp.stat(remote_path)
                except FileNotFoundError:
                    sftp.mkdir(remote_path)
                sftp_put_dir(sftp, local_path, remote_path)
                print(f"  Uploaded: {item}/")
            else:
                sftp.put(local_path, remote_path)
                print(f"  Uploaded: {item}")

    finally:
        sftp.close()

    # ── Run deploy.sh on VPS ───────────────────────────────────────────
    print("[4/5] Running setup script on VPS...")
    run(f"chmod +x {VPS_PATH}/deploy.sh")

    channel = ssh.get_transport().open_session()
    channel.exec_command(f"{VPS_PATH}/deploy.sh")
    channel.settimeout(120)

    # Stream output in real-time
    while True:
        if channel.exit_status_ready():
            break
        if channel.recv_ready():
            data = channel.recv(4096).decode()
            print(data, end="")
        time.sleep(0.2)

    # Drain remaining output
    while channel.recv_ready():
        print(channel.recv(4096).decode(), end="")

    exit_code = channel.recv_exit_status()

    # ── Verify ─────────────────────────────────────────────────────────
    print("[5/5] Verifying deployment...")

    code, tz_out, _ = run("timedatectl | grep 'Time zone'")
    print(f"  Timezone: {tz_out.strip()}")

    code, cron_out, _ = run(
        "cat /etc/cron.d/trading-bot 2>/dev/null || echo 'NO CRON FILE'"
    )
    print(f"  Cron:\n{cron_out.strip()}")

    ssh.close()

    print()
    if exit_code == 0:
        print("=== Deployment completed successfully ===")
    else:
        print(f"=== Deployment completed (deploy.sh exit code: {exit_code}) ===")

    print("Next steps:")
    print(f"  SSH: ssh root@{VPS_HOST}")
    print(f"  Test: cd {VPS_PATH} && .venv/bin/python start_bot.py")
    print("  Token log: tail -f /var/log/trading-bot/token.log")
    print("  Bot log:   tail -f /var/log/trading-bot/bot.log")


if __name__ == "__main__":
    main()
