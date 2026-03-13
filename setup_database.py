import sqlite3
import ast
import os

DB_NAME = "cctv_manager.db"
CONFIG_FILE = "cctvdevices.txt"

def initialize_and_migrate():
    # A. CREATE THE DATABASE AND TABLES
    print("🛠️ Creating Database...")
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cameras (
            ip TEXT PRIMARY KEY,
            name TEXT,
            location TEXT,
            status INTEGER DEFAULT 1,
            last_change TEXT DEFAULT 'Never',
            work_order TEXT DEFAULT 'None',
            is_pending INTEGER DEFAULT 0
        )
    ''')
    
    # B. IMPORT DATA FROM YOUR TEXT FILE
    if os.path.exists(CONFIG_FILE):
        print(f"📥 Reading data from {CONFIG_FILE}...")
        try:
            with open(CONFIG_FILE, 'r') as f:
                devices = ast.literal_eval(f.read().strip())
            
            count = 0
            for ip, info in devices.items():
                cursor.execute('''
                    INSERT OR IGNORE INTO cameras (ip, name, location)
                    VALUES (?, ?, ?)
                ''', (ip, info['name'], info.get('location', 'Unknown')))
                count += 1
            
            print(f"✅ Successfully migrated {count} cameras.")
        except Exception as e:
            print(f"❌ Migration Error: {e}")
    else:
        print("⚠️ No text file found. Creating an empty database for now.")

    conn.commit()
    conn.close()
    print(f"✨ Setup Complete! '{DB_NAME}' is ready.")

if __name__ == "__main__":
    initialize_and_migrate()
