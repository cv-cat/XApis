#!/usr/bin/env python3
"""Restore a console backup into an empty Docker MySQL database via private stdin.

Run after `docker compose stop web`. Uses the container's regular unprivileged
user, so host/container UID differences do not require weakening file modes.
"""

import argparse
import base64
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(
        description="恢复 XApis MySQL 备份（目标库必须为空）"
    )
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    running = subprocess.run(
        ["docker", "compose", "ps", "--status", "running", "-q", "web"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    if running.stdout.strip():
        parser.error("请先执行 docker compose stop web")
    bundle = {}
    for name in ("mysql-backup.json", "encryption.key", "setup.token"):
        path = args.folder.resolve() / name
        if name != "setup.token" or path.exists():
            bundle[name] = base64.b64encode(path.read_bytes()).decode()
    code = """import sys,json,base64,tempfile
from pathlib import Path
from console.store import Store
from console.backup import restore_backup,write_private
bundle=json.load(sys.stdin)
with tempfile.TemporaryDirectory() as directory:
 folder=Path(directory)
 for name in ('mysql-backup.json','encryption.key','setup.token'):
  if name in bundle:write_private(folder/name,base64.b64decode(bundle[name],validate=True))
 restore_backup(Store(),folder)
print('MySQL 备份和加密密钥已恢复，请重新启动 Web。')
"""
    subprocess.run(
        [
            "docker",
            "compose",
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "web",
            "python",
            "-c",
            code,
        ],
        cwd=root,
        input=json.dumps(bundle).encode(),
        check=True,
    )


if __name__ == "__main__":
    main()
