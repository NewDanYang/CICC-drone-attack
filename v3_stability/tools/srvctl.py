#!/usr/bin/env python3
"""TCEI host control: sh / get / put / ls.

  python srvctl.py sh "cmd"            # run a shell command
  python srvctl.py shf script.sh       # upload a local script and run it
  python srvctl.py get REMOTE [LOCAL]  # download a file (or dir)
  python srvctl.py put LOCAL REMOTE
  python srvctl.py ls REMOTE

Credentials come from the environment so this file can live in the repo:

  export TCEI_HOST=120.209.70.195 TCEI_PORT=30316 TCEI_USER=root
  export TCEI_PASSWORD='...'
"""
import os
import stat as statmod
import sys
import time
import paramiko

HOST = os.environ.get("TCEI_HOST", "120.209.70.195")
PORT = int(os.environ.get("TCEI_PORT", "30316"))
USER = os.environ.get("TCEI_USER", "root")
PASSWORD = os.environ.get("TCEI_PASSWORD", "")
HERE = os.path.dirname(os.path.abspath(__file__))


def client(attempts=6):
    """Connect with retries: this host intermittently drops the SSH banner,
    typically when it is heavily loaded (load avg > 4) or rate-limiting."""
    last = None
    for i in range(attempts):
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            c.connect(HOST, port=PORT, username=USER, password=PASSWORD,
                      look_for_keys=False, allow_agent=False, timeout=30,
                      banner_timeout=90, auth_timeout=60)
            return c
        except Exception as exc:
            last = exc
            try:
                c.close()
            except Exception:
                pass
            time.sleep(2 + 2 * i)
    raise SystemExit(f"SSH connect failed after {attempts} attempts: {last}")


def sh(cmd, timeout=600):
    c = client()
    try:
        _, out, err = c.exec_command(cmd, timeout=timeout)
        o = out.read().decode("utf-8", "replace")
        e = err.read().decode("utf-8", "replace")
        rc = out.channel.recv_exit_status()
    finally:
        c.close()
    # The Windows console defaults to GBK here; remote output can carry
    # characters it cannot encode (mojibake CJK from the ROS logs). Never let
    # that crash the helper -- replace unencodable chars instead.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.stdout.write(o)
    if e:
        sys.stderr.write("\n[stderr]\n" + e)
    return rc


def get(remote, local=None):
    if local is None:
        local = os.path.join(HERE, "srv_src", os.path.basename(remote.rstrip("/")))
    os.makedirs(os.path.dirname(local) or ".", exist_ok=True)
    c = client()
    try:
        s = c.open_sftp()
        s.get(remote, local)
        s.close()
    finally:
        c.close()
    print(f"got {remote} -> {local}")


def put(local, remote):
    """Write a local file to the remote host via a base64 pipe over exec.

    SFTP is unreliable on this host (intermittent ENOENT on stat/open), so
    avoid it entirely and stream through the shell's stdin instead.
    """
    import base64
    with open(local, "rb") as fh:
        payload = base64.b64encode(fh.read())
    c = client()
    try:
        cmd = f"base64 -d > {remote}"
        _, out, err = c.exec_command(cmd, timeout=300)
        out.channel.sendall(payload + b"\n")
        out.channel.shutdown_write()
        rc = out.channel.recv_exit_status()
        e = err.read().decode("utf-8", "replace")
    finally:
        c.close()
    if rc != 0:
        raise SystemExit(f"put failed rc={rc}: {e}")
    print(f"put {local} -> {remote} ({len(payload)} b64 bytes)")


def cat(local):
    """Print a local file's contents as a heredoc payload for remote writing."""
    with open(local, "r", encoding="utf-8") as fh:
        sys.stdout.write(fh.read())


def ls(remote):
    c = client()
    try:
        s = c.open_sftp()
        for a in sorted(s.listdir_attr(remote), key=lambda a: a.filename):
            kind = "d" if statmod.S_ISDIR(a.st_mode) else "-"
            print(f"{kind} {a.st_size:>10} {a.filename}")
        s.close()
    finally:
        c.close()


def run_script(local, args=""):
    remote = "/tmp/" + os.path.basename(local)
    put(local, remote)
    return sh(f"bash {remote} {args}")


if __name__ == "__main__":
    op = sys.argv[1]
    if op == "sh":
        sys.exit(sh(sys.argv[2]))
    if op == "shf":
        sys.exit(run_script(sys.argv[2], " ".join(sys.argv[3:])))
    if op == "get":
        get(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    elif op == "put":
        put(sys.argv[2], sys.argv[3])
    elif op == "ls":
        ls(sys.argv[2])
    else:
        sys.exit(f"unknown op {op}")
