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
    
    cursor.execute('''import sqlite3
import os
import csv

DB_NAME = "cctv_manager.db"
CONFIG_FILE = "cameras_list.csv"

def initialize_and_migrate():
    print("🛠️ Initializing Professional Database...")
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # 1. CREATE THE TABLE WITH THE EXACT SCHEMA REQUIRED (now includes incident_id)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cameras (
            ip TEXT PRIMARY KEY,
            name TEXT,
            location TEXT,
            status INTEGER DEFAULT 1,
            last_change TEXT DEFAULT 'Never',
            mail_eligible INTEGER DEFAULT 0,
            work_order TEXT DEFAULT NULL,
            comment TEXT DEFAULT NULL,
            down_time TEXT DEFAULT NULL,
            downtime_duration TEXT DEFAULT NULL,
            maintenance_mode INTEGER DEFAULT 0,
            incident_id TEXT DEFAULT NULL
        )
    ''')

    # 2. AUTO-REPAIR: Add any missing columns if the DB already exists
    required_columns = {
        'mail_eligible': 'INTEGER DEFAULT 0',
        'work_order': 'TEXT',
        'comment': 'TEXT',
        'down_time': 'TEXT',
        'downtime_duration': 'TEXT',
        'maintenance_mode': 'INTEGER DEFAULT 0',
        'incident_id': 'TEXT'
    }

    cursor.execute("PRAGMA table_info(cameras)")
    existing_cols = [col[1] for col in cursor.fetchall()]

    for col_name, col_type in required_columns.items():
        if col_name not in existing_cols:
            print(f"🔧 Repairing: Adding missing column '{col_name}'...")
            cursor.execute(f"ALTER TABLE cameras ADD COLUMN {col_name} {col_type}")

    # 3. IMPORT DATA FROM CSV
    if os.path.exists(CONFIG_FILE):
        print(f"📥 Reading data from {CONFIG_FILE}...")
        try:
            # We use utf-8-sig to handle Excel-saved CSVs
            with open(CONFIG_FILE, 'r', encoding='utf-8-sig') as f:
                reader = csv.reader(f)
                header = next(reader, None)  # Skip header row
                
                count = 0
                for row in reader:
                    if len(row) < 3:
                        continue
                    
                    ip, name, location = row[0].strip(), row[1].strip(), row[2].strip()
                    
                    # Insert new or update existing name/location
                    cursor.execute('''
                        INSERT INTO cameras (ip, name, location)
                        VALUES (?, ?, ?)
                        ON CONFLICT(ip) DO UPDATE SET 
                            name=excluded.name, 
                            location=excluded.location
                    ''', (ip, name, location))
                    count += 1
            
            print(f"✅ Successfully processed {count} cameras.")
        except Exception as e:
            print(f"❌ Migration Error: {e}")
    else:
        print(f"⚠️ {CONFIG_FILE} not found. Skipping data import.")

    conn.commit()
    conn.close()
    print(f"✨ Setup Complete! '{DB_NAME}' is now fully compatible with Master Console V6.2 (with incident_id).")

if __name__ == "__main__":
    initialize_and_migrate()
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
