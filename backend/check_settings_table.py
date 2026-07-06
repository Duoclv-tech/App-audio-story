"""Check settings table structure and test save"""
from app.database import SessionLocal
from sqlalchemy import text
from app import models

db = SessionLocal()
try:
    # Check table structure
    result = db.execute(text('DESCRIBE settings'))
    print('\nSettings table structure:')
    print('=' * 70)
    for row in result:
        print(f'{row[0]:<20} | {row[1]:<25} | {row[2]:<5} | {str(row[4]) if row[4] else ""}')
    print('=' * 70)

    # Check existing settings
    settings = db.query(models.Setting).all()
    print(f'\nExisting settings count: {len(settings)}')
    if settings:
        print('\nCurrent settings:')
        for setting in settings:
            print(f'  - {setting.setting_key}: {setting.setting_value}')

    # Test insert
    print('\n[TEST] Inserting test setting...')
    test_setting = models.Setting(
        setting_key='TEST_SETTING',
        setting_value='test_value_123'
    )
    db.add(test_setting)
    db.commit()
    print('[OK] Test setting saved!')

    # Verify
    verify = db.query(models.Setting).filter(
        models.Setting.setting_key == 'TEST_SETTING'
    ).first()
    print(f'[VERIFY] Retrieved value: {verify.setting_value}')

    # Cleanup
    db.delete(verify)
    db.commit()
    print('[CLEANUP] Test setting deleted')

except Exception as e:
    print(f'[ERROR] {e}')
    db.rollback()
finally:
    db.close()
