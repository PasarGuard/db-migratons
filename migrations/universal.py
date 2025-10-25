"""
migrations/universal.py

Universal database migration tool supporting direct database-to-database migration.
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime

try:
    from sqlalchemy import text, create_engine, inspect
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )
    import yaml
except ImportError:
    print("Error: Required packages not installed.")
    print("Install with: uv sync")
    sys.exit(1)


class UniversalMigrator:
    """
    Universal migrator class supporting both SQL dumps and live database sources.

    Instantiate with:
        migrator = UniversalMigrator(source, target_type, target_url, source_type=None)
        await migrator.run()
    """

    def __init__(
        self,
        source: str,
        target_type: str,
        target_url: str,
        source_type: str = None,
        exclude_tables: list = None,
        table_order: list = None,
        enum_defaults: dict = None,
        truncate_strings: bool = False,
    ):
        self.source = source
        self.source_type = (
            source_type  # 'postgres', 'mysql', 'sqlite', or None for auto-detect
        )
        self.target_type = target_type  # 'postgres', 'mysql', 'sqlite'
        self.target_url = target_url
        self.source_engine = None
        self.target_engine = None
        self.session_maker = None
        self.tables = {}
        self.create_statements = {}
        self.is_source_live = False
        self.is_target_async = target_type == "postgres"
        self.exclude_tables = set(exclude_tables or [])
        self.table_order = table_order or self._get_default_table_order()
        # If enum_defaults is None, use fallback. If it's an empty dict {}, respect that (no defaults)
        self.enum_defaults = (
            self._get_default_enum_defaults()
            if enum_defaults is None
            else enum_defaults
        )
        self.truncate_strings = truncate_strings
        self.truncation_warnings = []  # Track truncated columns for reporting

    def _get_default_table_order(self) -> list:
        """Get default table order (customizable via config file)"""
        return [
            # System/configuration tables (no dependencies)
            "jwt",
            "system",
            "settings",
            # Core tables
            "admins",
            "core_configs",
            "nodes",
            "inbounds",
            "groups",
            # Association tables
            "inbounds_groups_association",
            # Dependent tables
            "hosts",
            "user_templates",
            "template_group_association",
            # User tables
            "users",
            "users_groups_association",
            "next_plans",
            # Usage and log tables
            "admin_usage_logs",
            "user_usage_logs",
            "notification_reminders",
            "user_subscription_updates",
            "node_user_usages",
            "node_usages",
            "node_stats",
        ]

    def _get_default_enum_defaults(self) -> dict:
        """Get default enum/string column default values (customizable via config file)"""
        return {
            "fingerprint": "none",
            "security": "inbound_default",
        }

    def detect_source_type(self) -> bool:
        """Detect if source is SQL file or database"""
        if os.path.isfile(self.source):
            if self.source.endswith(".sql"):
                self.is_source_live = False
                return True
            elif (
                self.source.endswith(".db")
                or self.source.endswith(".sqlite")
                or self.source.endswith(".sqlite3")
            ):
                self.is_source_live = True
                self.source_type = "sqlite"
                return True
        # Check if it's a database URL
        if any(
            self.source.startswith(prefix)
            for prefix in ["postgresql://", "mysql://", "sqlite://"]
        ):
            self.is_source_live = True
            if self.source.startswith("postgresql://"):
                self.source_type = "postgres"
            elif self.source.startswith("mysql://"):
                self.source_type = "mysql"
            elif self.source.startswith("sqlite://"):
                self.source_type = "sqlite"
            return True
        return False

    async def connect_source(self):
        """Connect to source database if it's a live database"""
        if self.is_source_live:
            if self.source_type == "sqlite":
                # Handle SQLite file path
                if not self.source.startswith("sqlite:///"):
                    source_url = f"sqlite:///{self.source}"
                else:
                    source_url = self.source
                self.source_engine = create_engine(
                    source_url, pool_pre_ping=True, echo=False
                )
            else:
                self.source_engine = create_engine(
                    self.source, pool_pre_ping=True, echo=False
                )
            print(f"✓ Connected to source {self.source_type.upper()}")

    async def connect_target(self):
        """Connect to target database"""
        if self.is_target_async:
            self.target_engine = create_async_engine(
                self.target_url, pool_pre_ping=True, echo=False
            )
            self.session_maker = async_sessionmaker(
                self.target_engine, class_=AsyncSession, expire_on_commit=False
            )
        else:
            self.target_engine = create_engine(
                self.target_url, pool_pre_ping=True, echo=False
            )
        print(f"✓ Connected to target {self.target_type.upper()}")

    async def close(self):
        """Close connections"""
        if self.source_engine:
            self.source_engine.dispose()
        if self.target_engine:
            if self.is_target_async:
                await self.target_engine.dispose()
            else:
                self.target_engine.dispose()

    def read_from_database(self):
        """Read data from live source database"""
        print(f"\nReading from {self.source_type.upper()} database...")

        inspector = inspect(self.source_engine)
        table_names = inspector.get_table_names()

        with self.source_engine.connect() as conn:
            for table in table_names:
                # Skip excluded tables
                if table in self.exclude_tables:
                    print(f"  ⊘ {table} (excluded)")
                    continue

                # Get all rows
                result = conn.execute(text(f"SELECT * FROM {table}"))
                rows = result.fetchall()

                if rows:
                    columns = list(result.keys())
                    self.tables[table] = {
                        "columns": columns,
                        "rows": [list(row) for row in rows],
                    }

        print(f"✓ Read {len(self.tables)} tables with data")
        for name, data in self.tables.items():
            print(f"  • {name}: {len(data['rows'])} rows")

        if self.exclude_tables:
            print(
                f"✓ Excluded {len(self.exclude_tables)} tables: {', '.join(sorted(self.exclude_tables))}"
            )

    def parse_sql(self):
        """Parse SQL dump file"""
        print(f"\nReading {self.source}...")

        with open(self.source, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        is_sqlite = "CREATE TABLE" in content and "AUTOINCREMENT" in content.upper()

        # Parse CREATE TABLE statements with proper parenthesis matching
        create_pattern = re.compile(
            r"CREATE TABLE\s+[`'\"]?(\w+)[`'\"]?\s*\(", re.IGNORECASE
        )

        for match in create_pattern.finditer(content):
            table = match.group(1)

            # Skip excluded tables
            if table in self.exclude_tables:
                continue

            start_pos = match.end() - 1  # Position of opening (

            # Find matching closing parenthesis
            end_pos = self._find_paren(content, start_pos)
            if end_pos != -1:
                definition = content[start_pos + 1 : end_pos]
                self.create_statements[table] = definition

                # Extract column order from CREATE TABLE for proper mapping
                if table not in self.tables:
                    self.tables[table] = {
                        "columns": self._extract_columns_from_create(definition),
                        "rows": [],
                    }

        # Match INSERT statements - handle semicolons in data by looking ahead for statement terminators
        # This matches until we find a semicolon followed by keywords or end of input
        insert_pattern = re.compile(
            r"INSERT\s+INTO\s+[`'\"]?(\w+)[`'\"]?\s+(\([^)]+\))?\s*VALUES\s+(.+?);\s*(?=(?:INSERT|LOCK|UNLOCK|ALTER|CREATE|DROP|/\*!|\s*$))",
            re.IGNORECASE | re.DOTALL,
        )

        for table, cols, values in insert_pattern.findall(content):
            # Skip excluded tables
            if table in self.exclude_tables:
                continue

            if table not in self.tables:
                self.tables[table] = {"columns": None, "rows": []}

            # If INSERT has column names, use those; otherwise keep the CREATE TABLE order
            if cols and not self.tables[table]["columns"]:
                parsed_cols = self._parse_columns(cols)
                self.tables[table]["columns"] = parsed_cols

            parsed_rows = self._parse_values(values)
            self.tables[table]["rows"].extend(parsed_rows)

        print(f"✓ Parsed {'SQLite' if is_sqlite else 'MySQL'} dump")
        print(f"✓ Found {len(self.create_statements)} table schemas")
        print(f"✓ Found {len(self.tables)} tables with data")
        for name, data in self.tables.items():
            print(f"  • {name}: {len(data['rows'])} rows")

        if self.exclude_tables:
            print(
                f"✓ Excluded {len(self.exclude_tables)} tables: {', '.join(sorted(self.exclude_tables))}"
            )

    def _parse_columns(self, cols: str) -> list:
        """Extract column names from INSERT statement"""
        cols = cols.strip()[1:-1]  # Remove ( )
        return [c.strip().strip('`"\'"') for c in cols.split(",") if c.strip()]

    def _extract_columns_from_create(self, definition: str) -> list:
        """Extract column names in order from CREATE TABLE definition"""
        columns = []
        # Match column definitions (column_name data_type ...)
        # This regex matches lines like: `id` int NOT NULL AUTO_INCREMENT,
        pattern = re.compile(r"^\s*[`\'\"]?(\w+)[`\'\"]?\s+\w+", re.MULTILINE)
        for match in pattern.finditer(definition):
            col_name = match.group(1)
            # Skip constraint keywords
            if col_name.upper() not in (
                "PRIMARY",
                "KEY",
                "UNIQUE",
                "CONSTRAINT",
                "FOREIGN",
                "INDEX",
                "FULLTEXT",
                "CHECK",
            ):
                columns.append(col_name)
        return columns

    def _parse_values(self, values_str: str) -> list:
        """Parse VALUES clause"""
        rows = []
        i = 0
        while i < len(values_str):
            while i < len(values_str) and values_str[i] in " \n\r\t,":
                i += 1
            if i >= len(values_str):
                break
            if values_str[i] == "(":
                end = self._find_paren(values_str, i)
                if end == -1:
                    break
                rows.append(self._parse_row(values_str[i + 1 : end]))
                i = end + 1
            else:
                i += 1
        return rows

    def _find_paren(self, text: str, start: int) -> int:
        """Find matching closing parenthesis"""
        depth = 0
        in_str = False
        str_char = None
        escape = False

        for i in range(start, len(text)):
            if escape:
                escape = False
                continue
            if text[i] == "\\":
                escape = True
                continue
            if text[i] in "\"'":
                if not in_str:
                    in_str = True
                    str_char = text[i]
                elif text[i] == str_char:
                    in_str = False
            elif text[i] == "(" and not in_str:
                depth += 1
            elif text[i] == ")" and not in_str:
                depth -= 1
                if depth == 0:
                    return i
        return -1

    def _parse_row(self, row: str) -> list:
        """Parse single row values"""
        values = []
        current = ""
        in_str = False
        str_char = None
        escape = False
        depth = 0

        for char in row:
            if escape:
                current += char
                escape = False
                continue
            if char == "\\" and in_str:
                escape = True
                current += char
                continue
            if char in "'\"" and not in_str:
                in_str = True
                str_char = char
                current += char
            elif char == str_char and in_str:
                in_str = False
                current += char
            elif char == "(" and not in_str:
                depth += 1
                current += char
            elif char == ")" and not in_str:
                depth -= 1
                current += char
            elif char == "," and not in_str and depth == 0:
                values.append(self._convert(current.strip()))
                current = ""
            else:
                current += char

        if current.strip():
            values.append(self._convert(current.strip()))
        return values

    def _convert(self, val: str):
        """Convert SQL value to Python"""
        val = val.strip()

        if val.upper() == "NULL":
            return None

        if (val.startswith("'") and val.endswith("'")) or (
            val.startswith('"') and val.endswith('"')
        ):
            unquoted = val[1:-1]
            return (
                unquoted.replace("\\'", "'")
                .replace('\\"', '"')
                .replace("\\n", "\n")
                .replace("\\\\", "\\")
            )

        if val.lower() in ("true", "false"):
            return val.lower() == "true"

        try:
            return float(val) if "." in val else int(val)
        except ValueError:
            return val

    async def _get_table_columns(self, table: str) -> dict:
        """Get target database column types, nullable info, and max length"""
        if self.is_target_async:
            async with self.session_maker() as session:
                result = await session.execute(
                    text(
                        "SELECT column_name, udt_name, is_nullable, column_default, character_maximum_length FROM information_schema.columns WHERE table_name = :t ORDER BY ordinal_position"
                    ),
                    {"t": table},
                )
                return {
                    row[0]: {
                        "type": row[1],
                        "nullable": row[2] == "YES",
                        "default": row[3],
                        "max_length": row[4],
                    }
                    for row in result.fetchall()
                }
        else:
            with self.target_engine.connect() as conn:
                if self.target_type == "mysql":
                    result = conn.execute(
                        text(
                            "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT, CHARACTER_MAXIMUM_LENGTH FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = :t ORDER BY ORDINAL_POSITION"
                        ),
                        {"t": table},
                    )
                    return {
                        row[0]: {
                            "type": row[1].lower(),
                            "nullable": row[2] == "YES",
                            "default": row[3],
                            "max_length": row[4],
                        }
                        for row in result.fetchall()
                    }
                else:  # sqlite
                    result = conn.execute(text(f"PRAGMA table_info({table})"))
                    # SQLite doesn't enforce max length, so we extract it from type definition
                    def extract_length(type_str):
                        import re
                        match = re.search(r'\((\d+)\)', type_str)
                        return int(match.group(1)) if match else None

                    return {
                        row[1]: {
                            "type": row[2].lower(),
                            "nullable": row[3] == 0,
                            "default": row[4],
                            "max_length": extract_length(row[2]),
                        }
                        for row in result.fetchall()
                    }

    def _get_default_value(self, col_info: dict, table: str, column: str):
        """Get default value for NOT NULL columns"""
        col_type = col_info["type"].lower()
        default = col_info.get("default")

        # Use database default if available
        if default is not None and default != "":
            # Parse PostgreSQL defaults
            if isinstance(default, str):
                # Format: 'value'::type or just 'value'
                if "::" in default:
                    # Extract value from format like 'value'::type
                    value_part = default.split("::")[0].strip()
                    if value_part.startswith("'") and value_part.endswith("'"):
                        return value_part.strip("'")
                    return value_part
                elif default.startswith("'") and default.endswith("'"):
                    return default.strip("'")
                elif default.isdigit():
                    return int(default)
                elif default in ("true", "false"):
                    return default == "true"
            return default

        # Provide sensible defaults based on column type and name
        if "bool" in col_type or "tinyint(1)" in col_type:
            return False

        if any(t in col_type for t in ["int", "bigint", "smallint"]):
            return 0

        if any(
            t in col_type for t in ["float", "real", "double", "numeric", "decimal"]
        ):
            return 0.0

        # For datetime fields
        if any(t in col_type for t in ["timestamp", "datetime", "timestamptz"]):
            return datetime.now()

        # For text/string fields
        if any(t in col_type for t in ["text", "varchar", "char", "character"]):
            # Check for configured enum defaults
            if column in self.enum_defaults:
                return self.enum_defaults[column]
            return ""

        # Default fallback
        return ""

    def _convert_type(self, val, col_type: str):
        """Convert value to target database type with intelligent type detection"""
        if val is None:
            return None

        col_type = col_type.lower()

        # Boolean
        if col_type in ("bool", "boolean", "tinyint(1)"):
            if isinstance(val, bool):
                return val
            if isinstance(val, int):
                return bool(val)
            return str(val).lower() in ("true", "1", "t", "yes")

        # BigInteger (counters, large numeric values)
        if "bigint" in col_type or "int8" in col_type:
            try:
                return int(val)
            except (ValueError, TypeError):
                return 0

        # Integer
        if any(t in col_type for t in ["int", "integer", "smallint"]):
            try:
                return int(val)
            except (ValueError, TypeError):
                return None

        # Float/Real (decimal numbers, percentages, coefficients, etc.)
        if any(
            t in col_type for t in ["float", "real", "double", "numeric", "decimal"]
        ):
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        # Timestamp/DateTime
        if any(t in col_type for t in ["timestamp", "datetime", "timestamptz"]):
            if isinstance(val, str):
                try:
                    # Handle SQLite datetime format with microseconds
                    if "." in val:
                        return datetime.strptime(val, "%Y-%m-%d %H:%M:%S.%f")
                    else:
                        return datetime.strptime(val, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    try:
                        # Try ISO format
                        return datetime.fromisoformat(val.replace("Z", "+00:00"))
                    except ValueError:
                        return None

        # JSON (configuration objects, structured data, etc.)
        if "json" in col_type or "jsonb" in col_type:
            if isinstance(val, (dict, list)):
                return json.dumps(val)
            if isinstance(val, str):
                # Validate it's valid JSON
                try:
                    json.loads(val)
                    return val
                except json.JSONDecodeError:
                    return val

        # Text/String (including StringArray, EnumArray - stored as comma-separated)
        if any(t in col_type for t in ["text", "varchar", "char", "character"]):
            return str(val) if val is not None else None

        return val

    def _truncate_if_needed(self, val: str, max_length: int, table: str, column: str) -> str:
        """Truncate string if it exceeds max length and truncation is enabled"""
        if not isinstance(val, str) or max_length is None:
            return val

        if len(val) > max_length:
            if self.truncate_strings:
                truncated = val[:max_length]
                warning_key = f"{table}.{column}"
                if warning_key not in self.truncation_warnings:
                    self.truncation_warnings.append(warning_key)
                return truncated
            # If truncation disabled, return as-is and let database error
            return val

        return val

    async def clear_data(self):
        """Clear target database tables"""
        print("\n⚠ WARNING: This will delete ALL data in the target database!")

        # Detect and display auto-increment tables
        auto_increment_tables = await self.detect_auto_increment_tables()
        if auto_increment_tables:
            print("\n📋 Tables with auto-increment columns that will be reset:")
            for table, column in sorted(auto_increment_tables.items()):
                print(f"  • {table}.{column}")

        print()
        resp = input("Type 'yes' to continue: ")
        if resp.lower() != "yes":
            print("Cancelled")
            sys.exit(0)

        print("\nClearing tables...")
        # Use custom table order in reverse (clear dependent tables first)
        tables = list(reversed(self.table_order))

        if self.is_target_async:
            # PostgreSQL: Use try/finally to ensure session_replication_role is always restored
            try:
                async with self.session_maker() as session:
                    await session.execute(
                        text("SET session_replication_role = 'replica';")
                    )
                    await session.commit()

                # Truncate each table in its own transaction to avoid cascading failures
                for table in tables:
                    async with self.session_maker() as session:
                        try:
                            await session.execute(
                                text(f"TRUNCATE TABLE {table} CASCADE")
                            )
                            await session.commit()
                            print(f"  ✓ {table}")
                        except Exception as e:
                            await session.rollback()
                            print(f"  ⚠ {table}: {str(e)[:50]}")
            finally:
                # CRITICAL: Always restore session_replication_role, even on errors
                async with self.session_maker() as session:
                    await session.execute(
                        text("SET session_replication_role = 'origin';")
                    )
                    await session.commit()
        else:
            if self.target_type == "mysql":
                with self.target_engine.begin() as conn:
                    conn.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))

            try:
                # Clear each table in its own transaction to avoid cascading failures
                for table in tables:
                    try:
                        with self.target_engine.begin() as conn:
                            if self.target_type == "mysql":
                                conn.execute(text(f"TRUNCATE TABLE {table}"))
                            else:
                                conn.execute(text(f"DELETE FROM {table}"))
                        print(f"  ✓ {table}")
                    except Exception as e:
                        print(f"  ⚠ {table}: {str(e)[:50]}")
            finally:
                # Ensure FOREIGN_KEY_CHECKS is always restored for MySQL
                if self.target_type == "mysql":
                    with self.target_engine.begin() as conn:
                        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))

    async def import_data(self):
        """Import all data"""
        print("\nImporting data...")

        # Use custom table order (import in dependency order)
        stats = {}

        for table in self.table_order:
            if table not in self.tables:
                continue

            # Skip migration framework tables (alembic_version, django_migrations, etc.)
            if table in (
                "alembic_version",
                "django_migrations",
                "flyway_schema_history",
                "schema_migrations",
            ):
                print(f"  ⊘ {table} (migration framework table - skipped)")
                continue

            if table in self.exclude_tables:
                print(f"  ⊘ {table} (excluded)")
                continue

            data = self.tables[table]
            rows = data["rows"]
            if not rows:
                continue

            print(f"  {table} ({len(rows)} rows)...", end=" ", flush=True)

            cols_dict = await self._get_table_columns(table)
            if not cols_dict:
                print("✗ table not found")
                continue

            cols = data["columns"] or list(cols_dict.keys())

            ok = 0
            fail = 0

            if self.is_target_async:
                batch_size = 5000  # Commit every 5000 rows for better performance

                # PostgreSQL: Use try/finally to ensure session_replication_role is always restored
                try:
                    async with self.session_maker() as session:
                        await session.execute(
                            text("SET session_replication_role = 'replica';")
                        )
                        await session.commit()

                        # Use bulk_insert_mappings for better performance
                        batch_data = []

                        for row_vals in rows:
                            row_vals = self._adjust_row(row_vals, cols)
                            converted = []
                            for c, v in zip(cols, row_vals):
                                col_info = cols_dict.get(
                                    c,
                                    {"type": "text", "nullable": True, "default": None},
                                )

                                # Preserve None/NULL values for nullable columns
                                if v is None and col_info["nullable"]:
                                    converted.append(None)
                                    continue

                                converted_val = self._convert_type(v, col_info["type"])

                                # Handle None values for NOT NULL columns
                                if converted_val is None and not col_info["nullable"]:
                                    converted_val = self._get_default_value(
                                        col_info, table, c
                                    )

                                # Apply string truncation if needed
                                if col_info.get("max_length"):
                                    converted_val = self._truncate_if_needed(
                                        converted_val, col_info["max_length"], table, c
                                    )

                                converted.append(converted_val)

                            params = dict(zip(cols, converted))
                            batch_data.append(params)

                            # Execute batch insert when batch size reached
                            if len(batch_data) >= batch_size:
                                try:
                                    # Use bulk insert for better performance
                                    sql = self._build_insert(table, cols)
                                    for data in batch_data:
                                        await session.execute(text(sql), data)
                                    await session.commit()
                                    ok += len(batch_data)
                                    batch_data = []
                                except Exception as e:
                                    await session.rollback()
                                    # Retry failed batch row-by-row to isolate problematic rows
                                    batch_ok = 0
                                    batch_fail = 0
                                    for data in batch_data:
                                        try:
                                            await session.execute(text(sql), data)
                                            await session.commit()
                                            batch_ok += 1
                                        except Exception as row_error:
                                            await session.rollback()
                                            batch_fail += 1
                                            if batch_fail <= 3:  # Print first 3 errors with details
                                                error_str = str(row_error)
                                                # Extract the specific column if mentioned in error
                                                print(f"\n    ✗ Error: {error_str[:200]}")
                                                # Print sample of row data for debugging
                                                sample_data = {k: (str(v)[:50] + '...' if isinstance(v, str) and len(str(v)) > 50 else v) for k, v in list(data.items())[:5]}
                                                print(f"      Sample data: {sample_data}")
                                    ok += batch_ok
                                    fail += batch_fail
                                    batch_data = []
                                    if batch_fail == 0 and fail <= 1:
                                        # Original batch error but all rows succeeded individually
                                        print(f"\n    ⚠ Batch failed but rows recovered: {str(e)[:100]}")

                        # Insert remaining rows
                        if batch_data:
                            try:
                                sql = self._build_insert(table, cols)
                                for data in batch_data:
                                    await session.execute(text(sql), data)
                                await session.commit()
                                ok += len(batch_data)
                            except Exception as e:
                                await session.rollback()
                                # Retry failed batch row-by-row
                                batch_ok = 0
                                batch_fail = 0
                                for data in batch_data:
                                    try:
                                        await session.execute(text(sql), data)
                                        await session.commit()
                                        batch_ok += 1
                                    except Exception as row_error:
                                        await session.rollback()
                                        batch_fail += 1
                                        if batch_fail <= 3:
                                            error_str = str(row_error)
                                            print(f"\n    ✗ Error: {error_str[:200]}")
                                            sample_data = {k: (str(v)[:50] + '...' if isinstance(v, str) and len(str(v)) > 50 else v) for k, v in list(data.items())[:5]}
                                            print(f"      Sample data: {sample_data}")
                                ok += batch_ok
                                fail += batch_fail
                finally:
                    # CRITICAL: Always restore session_replication_role, even on errors
                    async with self.session_maker() as session:
                        await session.execute(
                            text("SET session_replication_role = 'origin';")
                        )
                        await session.commit()
            else:
                # MySQL: Implement proper batch commits
                batch_size = 5000
                batch_data = []

                with self.target_engine.begin() as conn:
                    for row_vals in rows:
                        row_vals = self._adjust_row(row_vals, cols)
                        converted = []
                        for c, v in zip(cols, row_vals):
                            col_info = cols_dict.get(
                                c, {"type": "text", "nullable": True, "default": None}
                            )

                            # Preserve None/NULL values for nullable columns
                            if v is None and col_info["nullable"]:
                                converted.append(None)
                                continue

                            converted_val = self._convert_type(v, col_info["type"])

                            # Handle None values for NOT NULL columns
                            if converted_val is None and not col_info["nullable"]:
                                converted_val = self._get_default_value(
                                    col_info, table, c
                                )

                            # Apply string truncation if needed
                            if col_info.get("max_length"):
                                converted_val = self._truncate_if_needed(
                                    converted_val, col_info["max_length"], table, c
                                )

                            converted.append(converted_val)

                        params = dict(zip(cols, converted))
                        batch_data.append(params)

                        # Execute batch insert when batch size reached
                        if len(batch_data) >= batch_size:
                            try:
                                sql = self._build_insert(table, cols)
                                for data in batch_data:
                                    conn.execute(text(sql), data)
                                conn.commit()
                                ok += len(batch_data)
                                batch_data = []
                            except Exception as e:
                                conn.rollback()
                                # Retry failed batch row-by-row to isolate problematic rows
                                batch_ok = 0
                                batch_fail = 0
                                for data in batch_data:
                                    try:
                                        conn.execute(text(sql), data)
                                        conn.commit()
                                        batch_ok += 1
                                    except Exception as row_error:
                                        conn.rollback()
                                        batch_fail += 1
                                        if batch_fail <= 3:
                                            error_str = str(row_error)
                                            print(f"\n    ✗ Error: {error_str[:200]}")
                                            sample_data = {k: (str(v)[:50] + '...' if isinstance(v, str) and len(str(v)) > 50 else v) for k, v in list(data.items())[:5]}
                                            print(f"      Sample data: {sample_data}")
                                ok += batch_ok
                                fail += batch_fail
                                batch_data = []
                                if batch_fail == 0 and fail <= 1:
                                    print(f"\n    ⚠ Batch failed but rows recovered: {str(e)[:100]}")

                    # Insert remaining rows
                    if batch_data:
                        try:
                            sql = self._build_insert(table, cols)
                            for data in batch_data:
                                conn.execute(text(sql), data)
                            conn.commit()
                            ok += len(batch_data)
                        except Exception as e:
                            conn.rollback()
                            # Retry failed batch row-by-row
                            batch_ok = 0
                            batch_fail = 0
                            for data in batch_data:
                                try:
                                    conn.execute(text(sql), data)
                                    conn.commit()
                                    batch_ok += 1
                                except Exception as row_error:
                                    conn.rollback()
                                    batch_fail += 1
                                    if batch_fail <= 3:
                                        error_str = str(row_error)
                                        print(f"\n    ✗ Error: {error_str[:200]}")
                                        sample_data = {k: (str(v)[:50] + '...' if isinstance(v, str) and len(str(v)) > 50 else v) for k, v in list(data.items())[:5]}
                                        print(f"      Sample data: {sample_data}")
                            ok += batch_ok
                            fail += batch_fail

            if fail > 0:
                print(f"⚠ {ok} ok, {fail} failed")
            else:
                print(f"✓ {ok}")

            stats[table] = {"ok": ok, "fail": fail}

        # Summary
        print("\n" + "=" * 50)
        total_ok = sum(s["ok"] for s in stats.values())
        total_fail = sum(s["fail"] for s in stats.values())
        print(f"Imported: {total_ok} rows")
        if total_fail > 0:
            print(f"Failed: {total_fail} rows")
        print("=" * 50)

    def _adjust_row(self, row_vals: list, cols: list) -> list:
        """Adjust row length to match columns"""
        if len(row_vals) < len(cols):
            return list(row_vals) + [None] * (len(cols) - len(row_vals))
        elif len(row_vals) > len(cols):
            return row_vals[: len(cols)]
        return row_vals

    def _build_insert(self, table: str, cols: list) -> str:
        """Build INSERT SQL for target database"""
        placeholders = ", ".join([f":{c}" for c in cols])
        return f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"

    async def detect_auto_increment_tables(self) -> dict:
        """
        Auto-detect tables with auto-increment/serial columns.
        Returns dict: {table_name: column_name}
        """
        auto_increment_tables = {}

        if self.is_target_async:
            # PostgreSQL: Find sequences and their associated tables
            async with self.session_maker() as session:
                result = await session.execute(
                    text("""
                    SELECT
                        t.table_name,
                        c.column_name
                    FROM information_schema.tables t
                    JOIN information_schema.columns c
                        ON t.table_name = c.table_name
                    WHERE t.table_schema = 'public'
                        AND t.table_type = 'BASE TABLE'
                        AND c.column_default LIKE 'nextval%'
                    ORDER BY t.table_name;
                """)
                )

                for row in result.fetchall():
                    table_name, column_name = row
                    auto_increment_tables[table_name] = column_name
        else:
            # MySQL: Find tables with AUTO_INCREMENT columns
            with self.target_engine.connect() as conn:
                if self.target_type == "mysql":
                    result = conn.execute(
                        text("""
                        SELECT
                            TABLE_NAME,
                            COLUMN_NAME
                        FROM INFORMATION_SCHEMA.COLUMNS
                        WHERE TABLE_SCHEMA = DATABASE()
                            AND EXTRA LIKE '%auto_increment%'
                        ORDER BY TABLE_NAME;
                    """)
                    )

                    for row in result.fetchall():
                        table_name, column_name = row
                        auto_increment_tables[table_name] = column_name

        return auto_increment_tables

    async def get_max_id(self, table: str, id_column: str = "id") -> int:
        """Get maximum ID from a table"""
        if self.is_target_async:
            async with self.session_maker() as session:
                result = await session.execute(
                    text(f"SELECT MAX({id_column}) FROM {table}")
                )
                max_id = result.scalar()
                return max_id if max_id is not None else 0
        else:
            with self.target_engine.connect() as conn:
                result = conn.execute(text(f"SELECT MAX({id_column}) FROM {table}"))
                max_id = result.scalar()
                return max_id if max_id is not None else 0

    async def restart_sequences(self):
        """Restart PostgreSQL sequences and MySQL auto-increment after migration"""
        print("\nRestarting sequences/auto-increment...")

        # Auto-detect tables with auto-increment columns
        auto_increment_tables = await self.detect_auto_increment_tables()

        if not auto_increment_tables:
            print("  • No auto-increment columns detected")
            return

        # Process only tables that have data imported
        for table, id_column in auto_increment_tables.items():
            # Skip if table wasn't imported
            if table not in self.tables or not self.tables[table]["rows"]:
                continue

            max_id = await self.get_max_id(table, id_column)
            if max_id is None or max_id <= 0:
                continue

            next_id = max_id + 1

            if self.target_type == "postgres":
                # Get actual sequence name from PostgreSQL
                if self.is_target_async:
                    async with self.session_maker() as session:
                        result = await session.execute(
                            text(
                                f"SELECT pg_get_serial_sequence('{table}', '{id_column}')"
                            )
                        )
                        seq_name = result.scalar()

                        if seq_name:
                            await session.execute(
                                text(f"SELECT setval('{seq_name}', {next_id})")
                            )
                            await session.commit()
                            print(f"  ✓ {table}.{id_column}: set to {next_id}")
                else:
                    with self.target_engine.begin() as conn:
                        result = conn.execute(
                            text(
                                f"SELECT pg_get_serial_sequence('{table}', '{id_column}')"
                            )
                        )
                        seq_name = result.scalar()

                        if seq_name:
                            conn.execute(
                                text(f"SELECT setval('{seq_name}', {next_id})")
                            )
                            print(f"  ✓ {table}.{id_column}: set to {next_id}")

            elif self.target_type == "mysql":
                if self.is_target_async:
                    async with self.session_maker() as session:
                        await session.execute(
                            text(f"ALTER TABLE {table} AUTO_INCREMENT = {next_id}")
                        )
                        await session.commit()
                        print(f"  ✓ {table}.{id_column}: set to {next_id}")
                else:
                    with self.target_engine.begin() as conn:
                        conn.execute(
                            text(f"ALTER TABLE {table} AUTO_INCREMENT = {next_id}")
                        )

        print("✓ Sequences/auto-increment restarted")

    def _convert_create_table_to_sqlite(self, table: str, definition: str) -> str:
        """Convert MySQL CREATE TABLE to SQLite"""
        # Remove backticks
        definition = definition.replace("`", "")

        # Handle ENUM types - convert to TEXT and remove enum values
        definition = re.sub(r"\bENUM\([^)]+\)", "TEXT", definition, flags=re.IGNORECASE)

        # Convert data types (with size parameters)
        definition = re.sub(
            r"\bBIGINT\(\d+\)", "INTEGER", definition, flags=re.IGNORECASE
        )
        definition = re.sub(r"\bINT\(\d+\)", "INTEGER", definition, flags=re.IGNORECASE)
        definition = re.sub(
            r"\bSMALLINT\(\d+\)", "INTEGER", definition, flags=re.IGNORECASE
        )
        definition = re.sub(
            r"\bTINYINT\(\d+\)", "INTEGER", definition, flags=re.IGNORECASE
        )
        definition = re.sub(
            r"\bVARCHAR\(\d+\)", "TEXT", definition, flags=re.IGNORECASE
        )
        definition = re.sub(r"\bCHAR\(\d+\)", "TEXT", definition, flags=re.IGNORECASE)

        # Convert data types (without size)
        definition = re.sub(r"\bBIGINT\b", "INTEGER", definition, flags=re.IGNORECASE)
        definition = re.sub(r"\bINT\b", "INTEGER", definition, flags=re.IGNORECASE)
        definition = re.sub(r"\bSMALLINT\b", "INTEGER", definition, flags=re.IGNORECASE)
        definition = re.sub(r"\bTINYINT\b", "INTEGER", definition, flags=re.IGNORECASE)
        definition = re.sub(r"\bTEXT\b", "TEXT", definition, flags=re.IGNORECASE)
        definition = re.sub(r"\bLONGTEXT\b", "TEXT", definition, flags=re.IGNORECASE)
        definition = re.sub(r"\bMEDIUMTEXT\b", "TEXT", definition, flags=re.IGNORECASE)
        definition = re.sub(r"\bDATETIME\b", "TEXT", definition, flags=re.IGNORECASE)
        definition = re.sub(r"\bTIMESTAMP\b", "TEXT", definition, flags=re.IGNORECASE)
        definition = re.sub(r"\bDATE\b", "TEXT", definition, flags=re.IGNORECASE)
        definition = re.sub(r"\bDOUBLE\b", "REAL", definition, flags=re.IGNORECASE)
        definition = re.sub(r"\bFLOAT\b", "REAL", definition, flags=re.IGNORECASE)
        definition = re.sub(
            r"\bDECIMAL\(\d+,\d+\)", "REAL", definition, flags=re.IGNORECASE
        )
        definition = re.sub(r"\bJSON\b", "TEXT", definition, flags=re.IGNORECASE)
        definition = re.sub(r"\bBOOLEAN\b", "INTEGER", definition, flags=re.IGNORECASE)

        # Convert AUTO_INCREMENT to AUTOINCREMENT
        definition = re.sub(
            r"\bAUTO_INCREMENT\b", "AUTOINCREMENT", definition, flags=re.IGNORECASE
        )

        # Remove MySQL-specific keywords
        definition = re.sub(r"\bUNSIGNED\b", "", definition, flags=re.IGNORECASE)
        definition = re.sub(r"\bZEROFILL\b", "", definition, flags=re.IGNORECASE)
        definition = re.sub(r"\bCOLLATE\s+\w+", "", definition, flags=re.IGNORECASE)
        definition = re.sub(
            r"\bCHARACTER SET\s+\w+", "", definition, flags=re.IGNORECASE
        )
        definition = re.sub(
            r"\bON UPDATE CURRENT_TIMESTAMP\b", "", definition, flags=re.IGNORECASE
        )
        definition = re.sub(
            r"\bCOMMENT\s+\'[^\']*\'", "", definition, flags=re.IGNORECASE
        )

        # Remove KEY definitions (indexes)
        definition = re.sub(
            r",\s*PRIMARY KEY\s*\([^)]+\)", "", definition, flags=re.IGNORECASE
        )
        definition = re.sub(
            r",\s*KEY\s+\w+\s*\([^)]+\)", "", definition, flags=re.IGNORECASE
        )
        definition = re.sub(
            r",\s*UNIQUE KEY\s+\w+\s*\([^)]+\)", "", definition, flags=re.IGNORECASE
        )
        definition = re.sub(
            r",\s*INDEX\s+\w+\s*\([^)]+\)", "", definition, flags=re.IGNORECASE
        )
        definition = re.sub(
            r",\s*FULLTEXT\s+KEY\s+\w+\s*\([^)]+\)", "", definition, flags=re.IGNORECASE
        )

        # Remove CONSTRAINT FOREIGN KEY definitions
        definition = re.sub(
            r",\s*CONSTRAINT\s+\w+\s+FOREIGN KEY\s*\([^)]+\)\s*REFERENCES\s+\w+\s*\([^)]+\)(?:\s+ON\s+DELETE\s+\w+)?(?:\s+ON\s+UPDATE\s+\w+)?",
            "",
            definition,
            flags=re.IGNORECASE,
        )

        # Clean up extra spaces and commas
        definition = re.sub(r"\s+", " ", definition).strip()
        definition = re.sub(r",\s*,+", ",", definition)
        definition = re.sub(r",\s*\)", ")", definition)
        definition = re.sub(r"\(\s*,", "(", definition)

        return f"CREATE TABLE IF NOT EXISTS {table} ({definition})"

    async def create_schema(self):
        """Create database schema if needed (for SQLite targets)"""
        if self.target_type == "sqlite" and self.create_statements:
            print("\nCreating SQLite schema...")

            with self.target_engine.begin() as conn:
                # Use configured table order for schema creation
                for table in self.table_order:
                    if table in self.create_statements:
                        try:
                            create_sql = self._convert_create_table_to_sqlite(
                                table, self.create_statements[table]
                            )
                            conn.execute(text(create_sql))
                            print(f"  ✓ {table}")
                        except Exception as e:
                            print(f"  ✗ {table}: {str(e)[:70]}")
                            with open(f"debug_{table}_create.sql", "w") as f:
                                f.write(f"-- Error: {e}\n")
                                f.write(create_sql)
                            print(f"     Debug SQL saved to: debug_{table}_create.sql")

            print("✓ Schema created")

    async def run(self):
        """Run migration"""
        print("=" * 50)
        print(
            f"Database Migration: {self.source_type.upper() if self.source_type else 'SQL'} → {self.target_type.upper()}"
        )
        print("=" * 50)

        try:
            # Detect source type
            if not self.detect_source_type():
                print(f"\n✗ Error: Could not detect source type for '{self.source}'")
                return False

            # Read source data
            if self.is_source_live:
                await self.connect_source()
                self.read_from_database()
            else:
                self.parse_sql()

            # Connect and migrate
            await self.connect_target()
            await self.create_schema()  # Create schema for SQLite
            await self.clear_data()
            await self.import_data()
            await self.restart_sequences()  # Restart sequences for PostgreSQL
            print("\n✓ Migration completed!")
            return True
        except Exception as e:
            print(f"\n✗ Error: {e}")
            import traceback

            traceback.print_exc()
            return False
        finally:
            await self.close()


# CLI wrapper
def load_config_file(config_path: str) -> dict:
    """Load migration configuration from YAML file"""
    if not os.path.exists(config_path):
        print(f"Error: Config file '{config_path}' not found")
        sys.exit(1)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        if not config:
            print(f"Error: Config file '{config_path}' is empty")
            sys.exit(1)

        return config
    except yaml.YAMLError as e:
        print(f"Error: Invalid YAML in config file: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: Failed to read config file: {e}")
        sys.exit(1)


def parse_args():
    args = sys.argv[1:]

    # Check for config file first
    config_file = None
    if "--config" in args or "-c" in args:
        try:
            idx = args.index("--config") if "--config" in args else args.index("-c")
            if idx + 1 < len(args):
                config_file = args[idx + 1]
        except (ValueError, IndexError):
            pass

    if config_file:
        # Load from config file
        config = load_config_file(config_file)

        # Parse source
        source_config = config.get("source", {})
        if not source_config:
            print("Error: 'source' section not found in config file")
            sys.exit(1)

        source_type = source_config.get("type")
        source_path = source_config.get("path")
        source_url = source_config.get("url")

        if source_path:
            source = source_path
        elif source_url:
            source = source_url
        else:
            print(
                "Error: 'source.path' or 'source.url' must be specified in config file"
            )
            sys.exit(1)

        # Parse target
        target_config = config.get("target", {})
        if not target_config:
            print("Error: 'target' section not found in config file")
            sys.exit(1)

        target_type = target_config.get("type")
        target_path = target_config.get("path")
        target_url = target_config.get("url")

        if not target_type:
            print("Error: 'target.type' not specified in config file")
            sys.exit(1)

        if target_path:
            target_db = target_path
        elif target_url:
            target_db = target_url
        else:
            print(
                "Error: 'target.path' or 'target.url' must be specified in config file"
            )
            sys.exit(1)

        # Parse exclude_tables
        exclude_tables = config.get("exclude_tables", [])
        if isinstance(exclude_tables, str):
            exclude_tables = [t.strip() for t in exclude_tables.split(",")]

        # Parse table_order
        table_order = config.get("table_order")

        # Parse enum_defaults
        enum_defaults = config.get("enum_defaults")

        # Parse truncate_strings
        truncate_strings = config.get("truncate_strings", False)

        return (
            source,
            target_type,
            target_db,
            source_type,
            exclude_tables,
            table_order,
            enum_defaults,
            truncate_strings,
        )

    # Original command-line parsing
    if len(args) < 1 or "--help" in args or "-h" in args:
        print(__doc__)
        print("\nUsage:")
        print("  python universal.py <source> [OPTIONS]")
        print("  python universal.py --config <config.yml>  (recommended)")
        print("\nCommand Line Mode:")
        print("  <source>                Source file or database URL")
        print("\nOptions:")
        print("  --config, -c <file>     Load configuration from YAML file")
        print("  --to, -t <type>         Target database: postgres, mysql, sqlite")
        print("  --db, -d <url>          Target database connection URL or file path")
        print(
            "  --source-type <type>    Source database type (auto-detected if not specified)"
        )
        print("  --exclude-tables <list> Comma-separated list of tables to exclude")
        print("\nConfig File Format:")
        print("  source:")
        print("    type: mysql|postgres|sqlite")
        print("    path: <dump_file>  # For SQL dumps or SQLite files")
        print("    # OR")
        print("    url: <connection_url>  # For live database connections")
        print("  target:")
        print("    type: mysql|postgres|sqlite")
        print("    path: <output_file>  # For SQLite")
        print("    # OR")
        print("    url: <connection_url>  # For live databases (recommended)")
        print("  exclude_tables:  # Optional")
        print("    - table1")
        print("    - table2")
        print("\nExamples:")
        print("  # Using config file (recommended)")
        print("  python universal.py --config config.mysql-to-postgres.yml")
        print("\n  # Using command line")
        print(
            "  python universal.py backup.sql --to postgres --db postgresql+asyncpg://user:pass@localhost:5432/db"
        )
        print("\nSee config.example.yml for a complete configuration template")
        sys.exit(0 if "--help" in args or "-h" in args else 1)

    source = args[0]
    target_type = None
    target_db = None
    source_type = None
    exclude_tables = None
    table_order = None
    enum_defaults = None
    truncate_strings = False

    i = 1
    while i < len(args):
        if args[i] in ("--to", "-t") and i + 1 < len(args):
            target_type = args[i + 1].lower()
            i += 2
        elif args[i] in ("--db", "--target-db", "-d") and i + 1 < len(args):
            target_db = args[i + 1]
            i += 2
        elif args[i] == "--source-type" and i + 1 < len(args):
            source_type = args[i + 1].lower()
            i += 2
        elif args[i] in ("--exclude-tables", "-e") and i + 1 < len(args):
            exclude_tables = [t.strip() for t in args[i + 1].split(",")]
            i += 2
        else:
            i += 1

    return (
        source,
        target_type,
        target_db,
        source_type,
        exclude_tables,
        table_order,
        enum_defaults,
        truncate_strings,
    )


def get_user_input(prompt: str, default: str = None) -> str:
    if default:
        prompt = f"{prompt} [{default}]: "
    else:
        prompt = f"{prompt}: "
    value = input(prompt).strip()
    return value if value else default


async def main():
    (
        source,
        target_type,
        target_db,
        source_type,
        exclude_tables,
        table_order,
        enum_defaults,
        truncate_strings,
    ) = parse_args()

    if not os.path.exists(source) and not source.startswith(
        ("postgresql://", "mysql://", "sqlite://")
    ):
        print(f"Error: Source '{source}' not found")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("Universal Database Migration Tool")
    print("=" * 60)
    print(f"\nSource: {source}\n")

    # Get target type if not specified
    if not target_type:
        print("Target database types:")
        print("  1. PostgreSQL")
        print("  2. MySQL")
        print("  3. SQLite")

        choice = get_user_input("\nSelect target database (1-3)", "1")
        target_map = {"1": "postgres", "2": "mysql", "3": "sqlite"}
        target_type = target_map.get(choice, "postgres")

    # Get target database URL/path
    if not target_db:
        print(f"\nEnter {target_type.upper()} connection details:")

        if target_type == "postgres":
            print("Format: postgresql+asyncpg://user:password@host:port/database")
            target_db = get_user_input("PostgreSQL URL")

        elif target_type == "mysql":
            print("Format: mysql+pymysql://user:password@host:port/database")
            target_db = get_user_input("MySQL URL")

        elif target_type == "sqlite":
            print("Example: database.db")
            target_db = get_user_input("SQLite database file", "database.db")

    if not target_db:
        print("\nError: No database connection specified")
        sys.exit(1)

    # Format target URL for SQLAlchemy
    if target_type == "sqlite" and not target_db.startswith("sqlite:///"):
        target_db = f"sqlite:///{target_db}"

    # Display configuration
    print("\n" + "=" * 60)
    print("Migration Configuration:")
    print("=" * 60)
    print(f"Source: {source}")
    print(f"Target type: {target_type.upper()}")

    if target_type != "sqlite":
        # Mask password in URL
        masked = target_db
        if "@" in target_db and "//" in target_db:
            parts = target_db.split("//")
            if len(parts) > 1 and "@" in parts[1]:
                auth_host = parts[1].split("@")
                if ":" in auth_host[0]:
                    user = auth_host[0].split(":")[0]
                    masked = f"{parts[0]}//{user}:****@{auth_host[1]}"
        print(f"Connection: {masked}")
    else:
        print(f"Database: {target_db.replace('sqlite:///', '')}")
    print("=" * 60)

    if exclude_tables:
        print(f"Excluded tables: {', '.join(exclude_tables)}")
        print("=" * 60)

    resp = get_user_input("\nProceed with migration? (yes/no)", "no")
    if resp.lower() not in ("yes", "y"):
        print("Cancelled")
        sys.exit(0)

    migrator = UniversalMigrator(
        source,
        target_type,
        target_db,
        source_type,
        exclude_tables,
        table_order,
        enum_defaults,
        truncate_strings,
    )
    success = await migrator.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
