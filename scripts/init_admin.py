"""Local console-only first administrator initialization; never accepts password arguments."""
import asyncio
import getpass
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import database as db
from routers.auth import hash_password

async def main():
    await db.init_db()
    if await db.get_user_by_username("admin") or await db.get_admin_password_hash():
        raise SystemExit("Existing administrator found; initialization refused")
    password = getpass.getpass("New administrator password (12+ characters): ")
    if len(password) < 12 or password != getpass.getpass("Confirm password: "):
        raise SystemExit("Password validation failed")
    await db.create_user("admin", hash_password(password), "admin")
    print("Administrator initialized")

if __name__ == "__main__":
    asyncio.run(main())
