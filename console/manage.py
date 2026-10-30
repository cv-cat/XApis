"""Local administration; never expose setup or recovery through a public API."""

import argparse
import getpass
import os
from pathlib import Path
from console.store import Store
from console.security import password_hash


def main():
    parser = argparse.ArgumentParser(description="XApis 控制台管理")
    parser.add_argument(
        "command",
        choices=[
            "setup-token",
            "reset-password",
            "backup",
            "restore",
            "migrate-sqlite",
        ],
    )
    parser.add_argument("--username")
    parser.add_argument("--output", help="备份输出目录（包含加密密钥，需安全保存）")
    parser.add_argument("--source", help="恢复备份目录或旧 SQLite 文件")
    args = parser.parse_args()
    store = Store()
    if args.command == "setup-token":
        if store.one("SELECT id FROM users LIMIT 1"):
            parser.exit(
                1,
                "控制台已初始化，初始化令牌已不可用。需要恢复账户请使用 reset-password。\n",
            )
        print(store.setup_token)
    elif args.command == "reset-password":
        username = args.username or input("用户名：").strip()
        user = store.one("SELECT * FROM users WHERE username=?", (username,))
        if not user:
            parser.error("用户不存在")
        first = getpass.getpass("新密码（至少 12 位）：")
        second = getpass.getpass("再次输入：")
        if first != second or not 12 <= len(first) <= 128:
            parser.error("密码不一致或长度不符合要求")
        with store.connect() as db:
            db.execute(
                "UPDATE users SET password=?,disabled=0 WHERE id=?",
                (password_hash(first), user["id"]),
            )
            db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
        store.audit(user["id"], "auth.local-recovery")
        print("密码已更新，原会话已退出。")
    elif args.command == "backup":
        from console.backup import export_backup

        if not args.output:
            parser.error("请用 --output 指定新的备份目录")
        print("MySQL 一致性备份已写入：" + str(export_backup(store, args.output)))
    elif args.command == "restore":
        from console.backup import restore_backup

        if not args.source:
            parser.error("请用 --source 指定备份目录")
        restore_backup(store, args.source)
        print("备份已恢复，请重启 Web 服务。")
    elif args.command == "migrate-sqlite":
        from console.backup import migrate_sqlite

        if not args.source:
            parser.error("请用 --source 指定旧 SQLite 文件")
        print("已迁移到 MySQL：", migrate_sqlite(store, args.source))


if __name__ == "__main__":
    main()
