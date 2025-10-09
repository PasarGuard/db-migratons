#!/bin/bash

# PasarGuard Migration Tool
# Interactive database migration with menu-driven interface
#
# Usage: ./migrate.sh [options]
#

set -euo pipefail

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'
BOLD='\033[1m'

# Global variables
SOURCE_FILE=""
SOURCE_TYPE=""
TARGET_TYPE=""
TARGET_DB=""

echo_success() { echo -e "${GREEN}✓${NC} $1"; }
echo_error()   { echo -e "${RED}✗${NC} $1"; }
echo_info()    { echo -e "${YELLOW}ℹ${NC} $1"; }
echo_title()   { echo -e "${BOLD}${CYAN}$1${NC}"; }
echo_menu()    { echo -e "${BLUE}$1${NC}"; }

clear_screen() {
    clear
    echo -e "${BOLD}${MAGENTA}"
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║        PasarGuard Universal Database Migration             ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

press_enter() {
    echo ""
    echo -e "${CYAN}Press Enter to continue...${NC}"
    read -r
}

check_uv() {
    if ! command -v uv &>/dev/null; then
        clear_screen
        echo_info "uv not found. Installing uv..."
        echo ""

        # Try to install uv
        if curl -LsSf https://astral.sh/uv/install.sh | sh; then
            echo ""
            echo_success "uv installed successfully!"
            echo ""
            # Add uv to current PATH
            export PATH="$HOME/.cargo/bin:$PATH"

            # Verify installation
            if ! command -v uv &>/dev/null; then
                echo_error "uv installation succeeded but not found in PATH"
                echo "Please add to PATH: export PATH=\"\$HOME/.cargo/bin:\$PATH\""
                echo "Then run this script again."
                exit 1
            fi
        else
            echo ""
            echo_error "Failed to install uv automatically"
            echo ""
            echo "Please install manually:"
            echo -e "  ${CYAN}curl -LsSf https://astral.sh/uv/install.sh | sh${NC}"
            echo ""
            echo -e "Or visit: ${CYAN}https://github.com/astral-sh/uv${NC}"
            exit 1
        fi
    fi
    UV_VERSION=$(uv --version 2>&1 | awk '{print $2}')

    # Sync dependencies from pyproject.toml
    if [ ! -d ".venv" ]; then
        echo_info "Setting up virtual environment and installing dependencies..."
        echo ""
        if uv sync; then
            echo ""
            echo_success "Dependencies installed successfully!"
        else
            echo ""
            echo_error "Failed to install dependencies"
            exit 1
        fi
    fi
}

detect_source_type() {
    local source="$1"
    
    if [[ "$source" == *.db ]] || [[ "$source" == *.sqlite ]]; then
        echo "sqlite"
    elif [[ "$source" == *.sql ]]; then
        # Try to detect from content
        if [ -f "$source" ]; then
            if grep -q "AUTOINCREMENT" "$source" 2>/dev/null; then
                echo "sqlite"
            else
                echo "mysql"
            fi
        else
            echo "mysql"
        fi
    elif [[ "$source" == mysql://* ]] || [[ "$source" == mysql+* ]]; then
        echo "mysql"
    elif [[ "$source" == postgresql://* ]] || [[ "$source" == postgresql+* ]]; then
        echo "postgres"
    elif [[ "$source" == sqlite://* ]]; then
        echo "sqlite"
    else
        echo "unknown"
    fi
}

select_source() {
    while true; do
        clear_screen
        echo_title "Step 1: Select Source Database"
        echo ""
        echo_menu "1) SQLite database file (.db, .sqlite)"
        echo_menu "2) MySQL/MariaDB SQL dump (.sql)"
        echo_menu "3) PostgreSQL SQL dump (.sql)"
        echo_menu "4) MySQL database URL (mysql://...)"
        echo_menu "5) PostgreSQL database URL (postgresql://...)"
        echo_menu "0) Exit"
        echo ""
        echo -n "Choose source type [1-5, 0]: "
        read -r choice
        
        case "$choice" in
            1)
                echo ""
                echo -n "Enter SQLite database file path: "
                read -r SOURCE_FILE
                if [ -f "$SOURCE_FILE" ]; then
                    SOURCE_TYPE="sqlite"
                    echo_success "Source selected: $SOURCE_FILE"
                    press_enter
                    return 0
                else
                    echo_error "File not found: $SOURCE_FILE"
                    press_enter
                fi
                ;;
            2)
                echo ""
                echo -n "Enter MySQL SQL dump file path: "
                read -r SOURCE_FILE
                if [ -f "$SOURCE_FILE" ]; then
                    SOURCE_TYPE="mysql"
                    echo_success "Source selected: $SOURCE_FILE"
                    press_enter
                    return 0
                else
                    echo_error "File not found: $SOURCE_FILE"
                    press_enter
                fi
                ;;
            3)
                echo ""
                echo -n "Enter PostgreSQL SQL dump file path: "
                read -r SOURCE_FILE
                if [ -f "$SOURCE_FILE" ]; then
                    SOURCE_TYPE="postgres"
                    echo_success "Source selected: $SOURCE_FILE"
                    press_enter
                    return 0
                else
                    echo_error "File not found: $SOURCE_FILE"
                    press_enter
                fi
                ;;
            4)
                echo ""
                echo "Format: mysql+pymysql://user:password@host:port/database"
                echo -n "Enter MySQL URL: "
                read -r SOURCE_FILE
                SOURCE_TYPE="mysql"
                echo_success "Source selected"
                press_enter
                return 0
                ;;
            5)
                echo ""
                echo "Format: postgresql://user:password@host:port/database"
                echo -n "Enter PostgreSQL URL: "
                read -r SOURCE_FILE
                SOURCE_TYPE="postgres"
                echo_success "Source selected"
                press_enter
                return 0
                ;;
            0)
                clear_screen
                echo_info "Migration cancelled"
                exit 0
                ;;
            *)
                echo_error "Invalid choice"
                press_enter
                ;;
        esac
    done
}

select_target() {
    while true; do
        clear_screen
        echo_title "Step 2: Select Target Database"
        echo ""
        echo -e "${CYAN}Source: ${NC}$SOURCE_FILE (${SOURCE_TYPE})"
        echo ""
        echo_menu "1) PostgreSQL"
        echo_menu "2) MySQL/MariaDB"
        echo_menu "3) SQLite"
        echo_menu "0) Back to source selection"
        echo ""
        echo -n "Choose target type [1-3, 0]: "
        read -r choice
        
        case "$choice" in
            1)
                TARGET_TYPE="postgres"
                echo ""
                echo "Format: postgresql+asyncpg://user:password@host:port/database"
                echo -n "PostgreSQL URL: "
                read -r TARGET_DB
                
                if [ -n "$TARGET_DB" ]; then
                    echo_success "Target configured"
                    press_enter
                    return 0
                else
                    echo_error "URL cannot be empty"
                    press_enter
                fi
                ;;
            2)
                TARGET_TYPE="mysql"
                echo ""
                echo "Format: mysql+pymysql://user:password@host:port/database"
                echo -n "MySQL URL: "
                read -r TARGET_DB
                
                if [ -n "$TARGET_DB" ]; then
                    echo_success "Target configured"
                    press_enter
                    return 0
                else
                    echo_error "URL cannot be empty"
                    press_enter
                fi
                ;;
            3)
                TARGET_TYPE="sqlite"
                echo ""
                echo -n "SQLite database file (e.g., pasarguard.db): "
                read -r TARGET_DB
                
                if [ -n "$TARGET_DB" ]; then
                    if [[ ! "$TARGET_DB" == sqlite://* ]]; then
                        TARGET_DB="sqlite:///$TARGET_DB"
                    fi
                    echo_success "Target configured"
                    press_enter
                    return 0
                else
                    echo_error "Filename cannot be empty"
                    press_enter
                fi
                ;;
            0)
                return 1
                ;;
            *)
                echo_error "Invalid choice"
                press_enter
                ;;
        esac
    done
}

confirm_migration() {
    clear_screen
    echo_title "Migration Summary"
    echo ""
    echo -e "${BOLD}Source:${NC}"
    echo "  File/URL: $SOURCE_FILE"
    echo "  Type:     $SOURCE_TYPE"
    echo ""
    echo -e "${BOLD}Target:${NC}"
    echo "  Type:     $TARGET_TYPE"
    
    # Mask password in URL
    MASKED_TARGET="$TARGET_DB"
    if [[ "$MASKED_TARGET" == *@* ]] && [[ "$MASKED_TARGET" == *//* ]]; then
        MASKED_TARGET=$(echo "$MASKED_TARGET" | sed -E 's/(:\/\/[^:]+:)[^@]+(@)/\1****\2/')
    fi
    echo "  URL:      $MASKED_TARGET"
    echo ""
    echo -e "${YELLOW}⚠  This will DELETE all data in the target database!${NC}"
    echo ""
    echo -n "Proceed with migration? [yes/no]: "
    read -r confirm
    
    if [[ "$confirm" != "yes" ]] && [[ "$confirm" != "y" ]]; then
        echo_info "Migration cancelled"
        press_enter
        return 1
    fi
    return 0
}

get_migration_script() {
    local src="$1"
    local tgt="$2"
    
    case "${src}_to_${tgt}" in
        sqlite_to_postgres)
            echo "migrations/sqlite_to_postgres.py"
            ;;
        sqlite_to_mysql)
            echo "migrations/sqlite_to_mysql.py"
            ;;
        mysql_to_postgres)
            echo "migrations/mysql_to_postgres.py"
            ;;
        mysql_to_sqlite)
            echo "migrations/mysql_to_sqlite.py"
            ;;
        postgres_to_mysql|postgres_to_sqlite)
            # These don't have specific wrappers yet, use universal
            echo "migrations/universal.py"
            ;;
        *)
            echo "migrations/universal.py"
            ;;
    esac
}

run_migration() {
    clear_screen
    echo_title "Running Migration"
    echo ""
    
    SCRIPT=$(get_migration_script "$SOURCE_TYPE" "$TARGET_TYPE")
    
    echo_info "Using uv $UV_VERSION"
    echo_info "Migration script: $SCRIPT"
    echo ""
    echo "═══════════════════════════════════════════════════════════"
    echo ""
    
    # Run migration with uv
    if uv run "$SCRIPT" "$SOURCE_FILE" --to "$TARGET_TYPE" --db "$TARGET_DB"; then
        echo ""
        echo "═══════════════════════════════════════════════════════════"
        echo ""
        echo_success "Migration completed successfully!"
        return 0
    else
        echo ""
        echo "═══════════════════════════════════════════════════════════"
        echo ""
        echo_error "Migration failed!"
        return 1
    fi
}

main_menu() {
    while true; do
        clear_screen
        echo_menu "Main Menu"
        echo ""
        echo_menu "1) Start New Migration"
        echo_menu "2) Quick Migration (command line)"
        echo_menu "3) Help & Documentation"
        echo_menu "0) Exit"
        echo ""
        echo -n "Choose an option [1-3, 0]: "
        read -r choice
        
        case "$choice" in
            1)
                # Interactive migration workflow
                if select_source; then
                    if select_target; then
                        if confirm_migration; then
                            run_migration
                            press_enter
                        fi
                    fi
                fi
                ;;
            2)
                # Quick command line mode
                clear_screen
                echo_title "Quick Migration Mode"
                echo ""
                echo "Command format:"
                echo -e "  ${CYAN}./migrate.sh <source> --to <type> --db <target>${NC}"
                echo ""
                echo "Examples:"
                echo -e "  ${CYAN}./migrate.sh pasarguard.db --to postgres --db postgresql+asyncpg://user:pass@host:5432/db${NC}"
                echo -e "  ${CYAN}./migrate.sh dump.sql --to sqlite --db pasarguard.db${NC}"
                echo ""
                echo "Available target types: postgres, mysql, sqlite"
                press_enter
                ;;
            3)
                show_help
                ;;
            0)
                clear_screen
                echo_info "Thank you for using PasarGuard Migration Tool"
                exit 0
                ;;
            *)
                echo_error "Invalid choice"
                press_enter
                ;;
        esac
    done
}

show_help() {
    clear_screen
    echo_title "Help & Documentation"
    echo ""
    echo -e "${BOLD}Supported Source Types:${NC}"
    echo "  • SQLite database files (.db, .sqlite)"
    echo "  • MySQL/MariaDB SQL dumps (.sql)"
    echo "  • PostgreSQL SQL dumps (.sql)"
    echo "  • Live database connections (URL)"
    echo ""
    echo -e "${BOLD}Supported Target Types:${NC}"
    echo "  • PostgreSQL (async via asyncpg)"
    echo "  • MySQL/MariaDB (via pymysql)"
    echo "  • SQLite"
    echo ""
    echo -e "${BOLD}URL Formats:${NC}"
    echo -e "  PostgreSQL: ${CYAN}postgresql+asyncpg://user:pass@host:5432/database${NC}"
    echo -e "  MySQL:      ${CYAN}mysql+pymysql://user:pass@host:3306/database${NC}"
    echo -e "  SQLite:     ${CYAN}sqlite:///path/to/file.db${NC} or just ${CYAN}file.db${NC}"
    echo ""
    echo -e "${BOLD}Features:${NC}"
    echo "  ✓ Direct database-to-database migration"
    echo "  ✓ SQL dump file migration"
    echo "  ✓ Automatic schema conversion"
    echo "  ✓ Data type mapping"
    echo "  ✓ Preserves relationships"
    echo ""
    echo -e "${BOLD}Command Line Usage:${NC}"
    echo -e "  ${CYAN}./migrate.sh${NC}                           Interactive mode"
    echo -e "  ${CYAN}./migrate.sh --help${NC}                   Show this help"
    echo -e "  ${CYAN}./migrate.sh <source> --to <type> --db <url>${NC}"
    echo ""
    press_enter
}

# Parse command line arguments
if [ $# -eq 0 ]; then
    # No arguments - run interactive menu
    check_uv
    main_menu
elif [[ "$1" == "--help" ]] || [[ "$1" == "-h" ]]; then
    show_help
    exit 0
else
    # Command line mode
    check_uv
    
    SOURCE_FILE="$1"
    shift
    
    # Parse options
    while [ $# -gt 0 ]; do
        case "$1" in
            --to|-t)
                TARGET_TYPE="$2"
                shift 2
                ;;
            --db|-d)
                TARGET_DB="$2"
                shift 2
                ;;
            *)
                shift
                ;;
        esac
    done
    
    # Validate inputs
    if [ ! -f "$SOURCE_FILE" ] && [[ ! "$SOURCE_FILE" == *://* ]]; then
        echo_error "Source file not found: $SOURCE_FILE"
        exit 1
    fi
    
    if [ -z "$TARGET_TYPE" ] || [ -z "$TARGET_DB" ]; then
        echo_error "Missing required arguments"
        echo ""
        echo "Usage: $0 <source> --to <type> --db <url>"
        echo "Run '$0 --help' for more information"
        exit 1
    fi
    
    # Auto-detect source type
    SOURCE_TYPE=$(detect_source_type "$SOURCE_FILE")
    
    # Confirm and run
    clear_screen
    if confirm_migration; then
        run_migration
        exit $?
    else
        exit 1
    fi
fi
