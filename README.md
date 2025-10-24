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

### Method 1: Configuration File (Recommended)

Use a YAML configuration file for cleaner, reusable, and more secure migrations.

#### Step 1: Create a configuration file

```bash
cp config.example.yml config.yml
nano config.yml  # or use your preferred editor
```

Example `config.yml`:
```yaml
source:
  type: "mysql"
  path: "backup.sql"  # For SQL dumps or SQLite files
  # url: "mysql://user:pass@host:3306/db"  # For live database connections

target:
  type: "postgres"
  url: "postgresql+asyncpg://user:password@localhost:5432/mydb"

exclude_tables:  # Optional
  - admin_usage_logs
  - user_usage_logs
  - node_stats

table_order:  # Optional - customize for your schema
  - users           # Tables with no foreign key dependencies first
  - posts           # Tables that reference users
  - comments        # Tables that reference posts and users

enum_defaults:   # Optional - for enum-like string columns
  status: "pending"
  role: "user"
```

#### Step 2: Run migration

```bash
uv run migrations/universal.py --config config.yml
# Or short form:
uv run migrations/universal.py -c config.yml
```

**Benefits:**
- ✅ Clean and readable
- ✅ Reusable for repeated migrations

---

### Method 2: Interactive Mode

Simply run the script without arguments:

```bash
./migrate.sh
```

This will launch an interactive menu where you can:
1. Select your source database type
2. Configure your target database
3. Review the migration summary
4. Execute the migration

---

### Method 3: Command Line Mode

For quick one-off migrations:

```bash
./migrate.sh <source> --to <type> --db <target_url> [--exclude-tables <tables>]
```

#### Examples

**Migrate SQLite to PostgreSQL:**
```bash
./migrate.sh pasarguard.db --to postgres --db postgresql+asyncpg://user:pass@localhost:5432/mydb
```

**Migrate MySQL dump to PostgreSQL:**
```bash
./migrate.sh mysql_dump.sql --to postgres --db postgresql+asyncpg://admin:password@localhost:5432/pasarguard
```

**Migrate PostgreSQL to MySQL:**
```bash
./migrate.sh postgresql://user:pass@host:5432/sourcedb --to mysql --db mysql+pymysql://user:pass@host:3306/targetdb
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

### Custom Table Order

For custom database schemas, you can specify the order in which tables should be cleared and imported based on foreign key dependencies. This is crucial to avoid constraint violations during migration.

**In your config file:**
```yaml
table_order:
  - users            # No foreign keys - import first
  - categories       # No foreign keys
  - posts            # References users - import after users
  - tags             # No foreign keys
  - post_tags        # References posts and tags - import last
  - comments         # References posts and users
```

**Ordering rules:**
1. List tables with **no foreign key dependencies first**
2. List tables that **reference those tables next**
3. Continue in **dependency order**
4. If not specified, the tool uses the default PasarGuard schema order

**Why is this important?**
- Tables are cleared in **reverse order** to avoid FK violations during deletion
- Tables are imported in **specified order** to satisfy FK constraints during insertion
- Wrong order will cause "foreign key constraint violation" errors

### Enum/String Column Defaults

For columns with enum-like string values that are `NOT NULL` but may have `NULL` values in the source data, you can specify default values to use during migration.

**In your config file:**
```yaml
enum_defaults:
  status: "pending"       # Default for 'status' column
  role: "user"            # Default for 'role' column
  visibility: "public"    # Default for 'visibility' column
```

**Behavior:**
- If **not specified**: Uses PasarGuard defaults (`fingerprint: "none"`, `security: "inbound_default"`)
- If **set to `{}`**: Disables all enum defaults (uses empty strings for `NOT NULL` text columns)
- If **specified**: Uses your custom defaults

**When is this useful?**
- Migrating databases with enum-like string columns (e.g., `status`, `role`, `type`)
- Handling `NULL` values in source data for `NOT NULL` columns
- Ensuring data consistency during migration with sensible defaults

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

## Configuration Files

### Pre-made Templates

The repository includes example configuration files:

- **`config.example.yml`** - Complete template with all options and comments
- **`config.mysql-to-postgres.yml`** - MySQL → PostgreSQL migration example
- **`config.postgres-to-mysql.yml`** - PostgreSQL → MySQL migration example

### Config File Structure

```yaml
source:
  type: "mysql"          # postgres, mysql, or sqlite
  path: "backup.sql"     # For SQL dumps or SQLite files
  # OR
  url: "mysql://..."     # For live database connections

target:
  type: "postgres"       # postgres, mysql, or sqlite
  url: "postgresql+asyncpg://..."  # For live databases (recommended)
  # OR
  path: "output.db"      # For SQLite output

exclude_tables:          # Optional
  - admin_usage_logs
  - user_usage_logs

table_order:             # Optional - for custom schemas
  - users                # Order tables by foreign key dependencies
  - posts                # Tables with no FKs first, dependent tables later
  - comments

enum_defaults:           # Optional - enum column defaults
  status: "pending"      # Default value for 'status' column
  role: "user"           # Default value for 'role' column
```

---

## Safety Features

⚠️ **Warning**: The tool will DELETE all data in the target database before migration.

- ✅ Interactive confirmation required
- ✅ Shows auto-increment columns that will be reset
- ✅ Preview migration summary before execution
- ✅ Password masking in output
- ✅ Detailed error reporting
- ✅ Transaction support with proper rollback
- ✅ Batch operations (1000 rows per commit) for performance

## Migration Scripts

The project includes specialized migration scripts:

- `migrations/universal.py` - Universal migrator for all database types (recommended)

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
- `pyyaml` - YAML configuration file parser

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

