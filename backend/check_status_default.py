"""Check status column default value"""
from app.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    print('Checking status column:')
    result = db.execute(text("SHOW COLUMNS FROM audio_files WHERE Field = 'status'"))
    for row in result:
        print(f'Field: {row[0]}')
        print(f'Type: {row[1]}')
        print(f'Null: {row[2]}')
        print(f'Key: {row[3]}')
        print(f'Default: {row[4]}')
        print(f'Extra: {row[5]}')

        if row[4] != 'idle':
            print(f'\n[FIX] Setting default to "idle"...')
            db.execute(text("ALTER TABLE audio_files MODIFY COLUMN status VARCHAR(50) DEFAULT 'idle'"))
            db.commit()
            print('[OK] Default updated!')
        else:
            print('\n[OK] Default is already "idle"')

except Exception as e:
    print(f'[ERROR] {e}')
    db.rollback()
finally:
    db.close()
