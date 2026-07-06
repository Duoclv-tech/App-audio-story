"""
Database Migration Runner
Run SQL migrations from migrations folder
Usage: python run_migration.py [migration_file]
"""

import sys
import os
from pathlib import Path
from sqlalchemy import text
from app.database import SessionLocal, engine
from loguru import logger


def run_migration(migration_file: str):
    """Run a specific migration file"""

    migration_path = Path(__file__).parent / "migrations" / migration_file

    if not migration_path.exists():
        logger.error(f"Migration file not found: {migration_path}")
        return False

    logger.info(f"Running migration: {migration_file}")

    # Read migration file
    with open(migration_path, 'r', encoding='utf-8') as f:
        sql_content = f.read()

    # Split by semicolon and execute each statement
    statements = [stmt.strip() for stmt in sql_content.split(';') if stmt.strip() and not stmt.strip().startswith('--')]

    db = SessionLocal()
    try:
        for i, statement in enumerate(statements, 1):
            if statement:
                logger.info(f"Executing statement {i}/{len(statements)}...")
                logger.debug(f"SQL: {statement[:100]}...")

                # Execute statement
                db.execute(text(statement))
                db.commit()

                logger.success(f"Statement {i} executed successfully")

        logger.success(f"Migration '{migration_file}' completed successfully!")
        return True

    except Exception as e:
        logger.error(f"Error running migration: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def list_migrations():
    """List all available migrations"""
    migrations_dir = Path(__file__).parent / "migrations"

    if not migrations_dir.exists():
        logger.warning("No migrations directory found")
        return []

    migrations = sorted([f.name for f in migrations_dir.glob("*.sql")])
    return migrations


def main():
    """Main entry point"""

    # Check if specific migration file provided
    if len(sys.argv) > 1:
        migration_file = sys.argv[1]

        # Add .sql extension if not present
        if not migration_file.endswith('.sql'):
            migration_file += '.sql'

        success = run_migration(migration_file)
        sys.exit(0 if success else 1)

    # Otherwise, list available migrations and prompt
    migrations = list_migrations()

    if not migrations:
        logger.warning("No migration files found in migrations/ directory")
        return

    logger.info("Available migrations:")
    for i, migration in enumerate(migrations, 1):
        logger.info(f"  {i}. {migration}")

    print()
    choice = input("Enter migration number to run (or 'all' to run all): ").strip()

    if choice.lower() == 'all':
        logger.info("Running all migrations...")
        for migration in migrations:
            success = run_migration(migration)
            if not success:
                logger.error(f"Failed to run migration: {migration}")
                break
    else:
        try:
            index = int(choice) - 1
            if 0 <= index < len(migrations):
                run_migration(migrations[index])
            else:
                logger.error("Invalid migration number")
        except ValueError:
            logger.error("Invalid input. Please enter a number or 'all'")


if __name__ == "__main__":
    main()
