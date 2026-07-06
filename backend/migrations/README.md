# Database Migrations

This directory contains SQL migration files for database schema changes.

## Migration Files

Migration files are named with a numeric prefix for ordering:

- `001_update_audio_files_add_tts_tracking.sql` - Add TTS tracking fields to audio_files table

## Running Migrations

### Method 1: Using the migration runner script (Recommended)

```bash
# From backend directory
cd web_app/backend

# Activate virtual environment if not already activated
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Run specific migration
python run_migration.py 001_update_audio_files_add_tts_tracking.sql

# Or run interactively (will list all migrations)
python run_migration.py
```

### Method 2: Using MySQL command line

```bash
# From backend directory
mysql -u your_username -p your_database < migrations/001_update_audio_files_add_tts_tracking.sql
```

### Method 3: Using MySQL Workbench or other GUI tools

1. Open the migration SQL file
2. Execute the SQL statements in your database

## Creating New Migrations

When creating new migrations:

1. Use sequential numbering: `002_`, `003_`, etc.
2. Use descriptive names: `002_add_user_preferences_table.sql`
3. Include comments explaining the changes
4. Test the migration on a development database first
5. Make migrations reversible when possible (include DROP/ALTER statements if needed)

## Migration Naming Convention

Format: `{number}_{description}.sql`

Examples:
- `001_update_audio_files_add_tts_tracking.sql`
- `002_create_user_preferences_table.sql`
- `003_add_index_to_stories.sql`

## Notes

- Always backup your database before running migrations on production
- Migrations are run manually and are not automatically applied
- Check the migration file contents before running
- Some migrations may take time on large databases
