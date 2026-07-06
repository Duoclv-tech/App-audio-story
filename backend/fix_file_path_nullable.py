"""Fix file_path column to be nullable"""
from app.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    print('[1] Checking current file_path constraint...')
    result = db.execute(text("DESCRIBE audio_files"))
    for row in result:
        if row[0] == 'file_path':
            print(f'   file_path: {row[1]}, NULL={row[2]}')

    print('\n[2] Modifying file_path to nullable...')
    db.execute(text('ALTER TABLE audio_files MODIFY COLUMN file_path TEXT NULL'))
    db.commit()
    print('   [OK] Column modified!')

    print('\n[3] Verifying change...')
    result = db.execute(text("DESCRIBE audio_files"))
    for row in result:
        if row[0] == 'file_path':
            print(f'   file_path: {row[1]}, NULL={row[2]}')
            if row[2] == 'YES':
                print('   [SUCCESS] file_path is now nullable!')
            else:
                print('   [ERROR] file_path is still NOT NULL!')

except Exception as e:
    print(f'[ERROR] {e}')
    db.rollback()
finally:
    db.close()
