"""
Wrapper: SQLite → PostgreSQL
Usage:
  python sqlite_to_postgres.py <source.db|source.sql> [--db <postgres_url>]
If --db missing, interactive prompt will ask.
"""

import asyncio
import os
import sys

# Add parent directory to path to import universal module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migrations.universal import UniversalMigrator


def parse_args():
    args = sys.argv[1:]
    if len(args) < 1:
        print(__doc__)
        sys.exit(1)
    source = args[0]
    target_db = None
    exclude_tables = None
    i = 1
    while i < len(args):
        if args[i] in ("--db", "-d") and i + 1 < len(args):
            target_db = args[i + 1]
            i += 2
        elif args[i] in ("--exclude-tables", "-e") and i + 1 < len(args):
            exclude_tables = [t.strip() for t in args[i + 1].split(",")]
            i += 2
        else:
            i += 1
    return source, target_db, exclude_tables


def get_user_input(prompt, default=None):
    if default:
        prompt = f"{prompt} [{default}]: "
    else:
        prompt = f"{prompt}: "
    v = input(prompt).strip()
    return v if v else default


async def main():
    source, target_db, exclude_tables = parse_args()
    if not os.path.exists(source) and not source.startswith("sqlite://"):
        print(f"File not found: {source}")
        sys.exit(1)

    if not target_db:
        target_db = get_user_input(
            "PostgreSQL URL (postgresql+asyncpg://user:pass@host:port/db)",
            "postgresql+asyncpg://user:password@localhost:5432/targetdb",
        )

    migrator = UniversalMigrator(source, "postgres", target_db, "sqlite", exclude_tables, None)
    await migrator.run()


if __name__ == "__main__":
    asyncio.run(main())
