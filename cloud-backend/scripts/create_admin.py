"""创建管理员账号：python scripts/create_admin.py <account> <password>"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.security import hash_password
from app.db.database import SessionLocal, init_db
from app.db.models import User


def main() -> None:
    if len(sys.argv) != 3:
        print("用法: python scripts/create_admin.py <account> <password>")
        sys.exit(1)
    account, password = sys.argv[1], sys.argv[2]
    if len(account) < 3:
        print("账号至少 3 个字符")
        sys.exit(1)

    init_db()
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.account == account).first()
        if existing:
            print(f"账号已存在：{account}（role={existing.role}），如需重置密码请在管理后台操作")
            sys.exit(1)
        user = User(
            account=account,
            password_hash=hash_password(password),
            nickname="admin",
            role="admin",
            status="active",
        )
        db.add(user)
        db.commit()
        print(f"管理员创建成功：{account}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
