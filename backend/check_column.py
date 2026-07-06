from app.database import engine

conn = engine.raw_connection()
cursor = conn.cursor()
cursor.execute('DESCRIBE stories')
columns = cursor.fetchall()

print('Stories table columns:')
for col in columns:
    print(f'  {col[0]}: {col[1]}')

# Check specifically for is_favorite
cursor.execute("SHOW COLUMNS FROM stories LIKE 'is_favorite'")
result = cursor.fetchone()

if result:
    print('\n✓ is_favorite column exists!')
    print(f'  Type: {result[1]}')
    print(f'  Default: {result[4]}')
else:
    print('\n✗ is_favorite column NOT found!')

cursor.close()
conn.close()
