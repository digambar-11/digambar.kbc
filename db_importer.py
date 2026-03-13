import sqlite3
import csv
import os

# Ensure this matches your actual filename: cctv_monitoring.db or cctv_manager.db
DB_NAME = "cctv_manager.db" 
CSV_FILE = "cameras_list.csv"

def smart_sync_import():
    if not os.path.exists(CSV_FILE):
        print(f"❌ Error: {CSV_FILE} not found!")
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # --- ADDED THIS: Ensures the database is ready for the data ---
    cursor.execute('''CREATE TABLE IF NOT EXISTS cameras (
                        ip TEXT PRIMARY KEY, 
                        name TEXT, 
                        location TEXT, 
                        status INTEGER DEFAULT 1, 
                        last_change TEXT,
                        is_pending INTEGER DEFAULT 0,
                        work_order TEXT)''')

    new_cams = 0
    updated_cams = 0

    try:
        # utf-8-sig handles the "BOM" characters Excel often adds
        with open(CSV_FILE, mode='r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            next(reader, None) # Skip Header
            
            for row in reader:
                if len(row) < 3: continue
                ip, name, loc = row[0].strip(), row[1].strip(), row[2].strip()

                cursor.execute("SELECT location FROM cameras WHERE ip = ?", (ip,))
                existing_record = cursor.fetchone()

                if existing_record:
                    old_loc = existing_record[0]
                    
                    if old_loc != loc:
                        # Location changed: Update info and RESET status flags
                        cursor.execute("""
                            UPDATE cameras 
                            SET name = ?, location = ?, is_pending = 0, work_order = NULL 
                            WHERE ip = ?
                        """, (name, loc, ip))
                        updated_cams += 1
                    else:
                        # Only name changed or stayed same: Update name only
                        cursor.execute("UPDATE cameras SET name = ? WHERE ip = ?", (name, ip))
                else:
                    # New IP: Add fresh record
                    cursor.execute("""
                        INSERT INTO cameras (ip, name, location, status, is_pending) 
                        VALUES (?, ?, ?, 1, 0)
                    """, (ip, name, loc))
                    new_cams += 1
        
        conn.commit()
        print(f"✅ Sync Complete!")
        print(f"   - {new_cams} New cameras added.")
        print(f"   - {updated_cams} Locations/Names updated and reset.")
        
    except Exception as e:
        print(f"⚠️ Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    smart_sync_import()
