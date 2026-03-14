import sqlite3
import csv
import os

DB_NAME = "cctv_manager.db"
CSV_FILE = "cameras_list.csv"

def smart_sync_import():
    if not os.path.exists(CSV_FILE):
        print(f"❌ Error: {CSV_FILE} not found!")
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Ensure table exists and matches main console schema (including incident_id)
    cursor.execute('''CREATE TABLE IF NOT EXISTS cameras (
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
                    )''')

    # Auto-repair: add any missing columns if DB already exists
    required_columns = {
        'mail_eligible': 'INTEGER DEFAULT 0',
        'work_order': 'TEXT DEFAULT NULL',
        'comment': 'TEXT DEFAULT NULL',
        'down_time': 'TEXT DEFAULT NULL',
        'downtime_duration': 'TEXT DEFAULT NULL',
        'maintenance_mode': 'INTEGER DEFAULT 0',
        'incident_id': 'TEXT DEFAULT NULL',
    }

    cursor.execute("PRAGMA table_info(cameras)")
    existing_cols = [col[1] for col in cursor.fetchall()]

    for col_name, col_type in required_columns.items():
        if col_name not in existing_cols:
            try:
                cursor.execute(f"ALTER TABLE cameras ADD COLUMN {col_name} {col_type}")
            except sqlite3.OperationalError:
                # If it races / already added, just ignore
                pass

    new_cams = 0
    updated_cams = 0

    try:
        # utf-8-sig handles the "BOM" characters Excel often adds
        with open(CSV_FILE, mode='r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            next(reader, None)  # Skip Header
            
            for row in reader:
                if len(row) < 3:
                    continue

                ip, name, loc = row[0].strip(), row[1].strip(), row[2].strip()

                cursor.execute("SELECT location FROM cameras WHERE ip = ?", (ip,))
                existing_record = cursor.fetchone()

                if existing_record:
                    old_loc = existing_record[0]

                    if old_loc != loc:
                        # Location changed:
                        # - update name & location
                        # - reset incident-related fields so it's treated as a fresh asset state
                        cursor.execute("""
                            UPDATE cameras 
                            SET name = ?,
                                location = ?,
                                status = 1,
                                mail_eligible = 0,
                                work_order = NULL,
                                comment = NULL,
                                down_time = NULL,
                                downtime_duration = NULL,
                                incident_id = NULL
                            WHERE ip = ?
                        """, (name, loc, ip))
                        updated_cams += 1
                    else:
                        # Only name changed or stayed the same: update name only
                        cursor.execute(
                            "UPDATE cameras SET name = ? WHERE ip = ?",
                            (name, ip)
                        )
                else:
                    # New IP: add fresh record; defaults handle status/flags
                    cursor.execute("""
                        INSERT INTO cameras (ip, name, location)
                        VALUES (?, ?, ?)
                    """, (ip, name, loc))
                    new_cams += 1
        
        conn.commit()
        print(f"✅ Sync Complete!")
        print(f"   - {new_cams} new cameras added.")
        print(f"   - {updated_cams} locations updated and incident state reset.")
        
    except Exception as e:
        print(f"⚠️ Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    smart_sync_import()
