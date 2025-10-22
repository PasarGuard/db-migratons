# PasarGuard Database Migration Tool

A powerful, universal database migration tool supporting migrations between PostgreSQL, MySQL/MariaDB, and SQLite databases.

## Prerequisites

- **Python 3.8+**
- **uv** - Fast Python package installer and resolver

### Install uv

```bash
apt update && apt install -y build-essential
```

```bash
# Linux/macOS
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or visit: https://github.com/astral-sh/uv
```

```bash
source $HOME/.local/bin/env
```

## Installation

1. Clone the repository:
```bash
git clone https://github.com/PasarGuard/db-migratons.git
cd db-migratons
```

2. Make the migration script executable:
```bash
chmod +x migrate.sh
```

3. Install dependencies:
```bash
uv sync
```

That's it! Dependencies are managed via `pyproject.toml` and installed in a local virtual environment.

## Usage

### Interactive Mode

Simply run the script without arguments:

```bash
./migrate.sh
```

This will launch an interactive menu where you can:
1. Select your source database type
2. Configure your target database
3. Review the migration summary
4. Execute the migration

### Command Line Mode

For automation or scripting:

```bash
./migrate.sh <source> --to <type> --db <target_url> [--exclude-tables <tables>]
```

#### Examples

**Migrate SQLite to PostgreSQL:**
```bash
./migrate.sh pasarguard.db --to postgres --db postgresql+asyncpg://user:pass@localhost:5432/mydb
```

**Migrate MySQL dump to SQLite:**
```bash
./migrate.sh dump.sql --to sqlite --db output.db
```

**Migrate PostgreSQL to MySQL:**
```bash
./migrate.sh postgresql://user:pass@host:5432/sourcedb --to mysql --db mysql+pymysql://user:pass@host:3306/targetdb
```

**Migrate MySQL dump to PostgreSQL:**
```bash
./migrate.sh mysql_dump.sql --to postgres --db postgresql+asyncpg://admin:password@localhost:5432/pasarguard
```

**Exclude specific tables (for faster migration):**
```bash
./migrate.sh dump.sql --to postgres --db postgresql+asyncpg://user:pass@localhost:5432/mydb --exclude-tables admin_usage_logs,user_usage_logs,node_stats
```

## Database URL Formats

### PostgreSQL
```
postgresql+asyncpg://username:password@host:port/database
```

### MySQL/MariaDB
```
mysql+pymysql://username:password@host:port/database
```

### SQLite
```
sqlite:///path/to/database.db
# or simply: database.db
```

## Supported Migration Paths

| From ↓ / To → | PostgreSQL | MySQL | SQLite |
|---------------|------------|-------|--------|
| **PostgreSQL** | ➖ | ✅ | ✅ |
| **MySQL** | ✅ | ➖ | ✅ |
| **SQLite** | ✅ | ✅ | ➖ |

## How It Works

1. **Source Detection**: Automatically detects source type (SQL dump or live database)
2. **Data Extraction**: Parses SQL dumps or connects to live databases
3. **Schema Conversion**: Converts data types and schema between database systems
4. **Target Preparation**: Clears target database (with confirmation)
5. **Data Import**: Imports data with type conversion and validation
6. **Progress Reporting**: Shows detailed progress and error reporting

### Excluding Tables

You can exclude specific tables from migration to speed up the process or skip unnecessary data like logs:

```bash
--exclude-tables "table1,table2,table3"
```

**Common tables to exclude:**
- `admin_usage_logs` - Admin activity logs
- `user_usage_logs` - User activity logs
- `node_stats` - Historical node statistics
- `node_usages` - Node usage history
- `user_subscription_updates` - Subscription update history

## Data Type Mapping

The tool intelligently maps data types between databases:

| MySQL | PostgreSQL | SQLite |
|-------|------------|--------|
| BIGINT | BIGINT | INTEGER |
| VARCHAR | VARCHAR | TEXT |
| DATETIME | TIMESTAMP | TEXT |
| JSON | JSONB | TEXT |
| ENUM | VARCHAR | TEXT |
| TINYINT(1) | BOOLEAN | INTEGER |

## Safety Features

⚠️ **Warning**: The tool will DELETE all data in the target database before migration.

- Interactive confirmation required
- Preview migration summary before execution
- Password masking in output
- Detailed error reporting
- Transaction support where available

## Migration Scripts

The project includes specialized migration scripts:

- `migrations/universal.py` - Universal migrator for all database types
- `migrations/mysql_to_postgres.py` - MySQL to PostgreSQL migration
- `migrations/mysql_to_sqlite.py` - MySQL to SQLite migration
- `migrations/sqlite_to_postgres.py` - SQLite to PostgreSQL migration
- `migrations/sqlite_to_mysql.py` - SQLite to MySQL migration

## Troubleshooting

### Common Issues

**uv not found:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Connection errors:**
- Verify database credentials
- Check network connectivity
- Ensure database server is running
- Verify port numbers and hostnames

**Permission errors:**
```bash
chmod +x migrate.sh
```

**Type conversion errors:**
- Check the migration output for specific errors
- Some complex types may need manual adjustment
- Review the data type mapping table above

## Dependencies

The tool automatically manages these dependencies via `uv`:

- `sqlalchemy` - Database toolkit and ORM
- `asyncpg` - PostgreSQL async driver
- `pymysql` - MySQL driver

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## Support

For issues, questions, or contributions, please visit:
https://github.com/PasarGuard/db-migratons
https://t.me/PasarGuardGP

## Acknowledgments

- Built with [SQLAlchemy](https://www.sqlalchemy.org/)
- Dependency management by [uv](https://github.com/astral-sh/uv)
- Async PostgreSQL support via [asyncpg](https://github.com/MagicStack/asyncpg)

---

Made with ❤️ by PasarGuard

