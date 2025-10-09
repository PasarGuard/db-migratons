#!/usr/bin/env python3
"""
Wrapper: MySQL → SQLite
Usage:
  python mysql_to_sqlite.py <source.sql|mysql_url> [--db <sqlite_file>]
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
    i = 1
    while i < len(args):
        if args[i] in ('--db', '-d') and i+1 < len(args):
            target_db = args[i+1]
            i += 2
        else:
            i += 1
    return source, target_db

def get_user_input(prompt, default=None):
    if default:
        prompt = f"{prompt} [{default}]: "
    else:
        prompt = f"{prompt}: "
    v = input(prompt).strip()
    return v if v else default

async def main():
    source, target_db = parse_args()
    
    # Check if source exists (file) or is a URL
    if not os.path.exists(source) and not source.startswith('mysql://'):
        print(f"File not found: {source}")
        sys.exit(1)

    if not target_db:
        target_db = get_user_input("SQLite database file", "pasarguard.db")

    if not target_db.startswith("sqlite:///"):
        target_db = f"sqlite:///{target_db}"

    migrator = UniversalMigrator(source, "sqlite", target_db, "mysql")
    await migrator.run()

if __name__ == "__main__":
    asyncio.run(main())
