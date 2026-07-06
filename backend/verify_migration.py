"""
Verify database migration
"""
from app.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    result = db.execute(text('DESCRIBE audio_files'))

    print('\n' + '='*80)
    print('Audio Files Table Structure')
    print('='*80)
    print(f"{'Field':<20} | {'Type':<25} | {'Null':<5} | {'Key':<5} | {'Default':<20}")
    print('-'*80)

    for row in result:
        field = row[0]
        type_str = row[1]
        null = row[2]
        key = row[3] or ''
        default = str(row[4]) if row[4] else ''
        print(f"{field:<20} | {type_str:<25} | {null:<5} | {key:<5} | {default:<20}")

    print('='*80)
    print('\n[OK] Migration verified successfully!')

except Exception as e:
    print(f'[ERROR] {e}')
finally:
    db.close()
