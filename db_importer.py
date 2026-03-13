import sqlite3
import csv
import os

DB_NAME = "cctv_manager.db"
CSV_FILE = "cameras_list.csv" #your excel file 

def import_from_csv():
    if not os.path.exists(CSV_FILE):
        print(f"❌ Error: {CSV_FILE} not found! Please place it in this folder.")
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Ensure the table exists before importing
    cursor.execute('''CREATE TABLE IF NOT EXISTS cameras (
                        ip TEXT PRIMARY KEY, 
                        name TEXT, 
                        location TEXT, 
                        status INTEGER DEFAULT 1, 
                        last_change TEXT,
                        is_pending INTEGER DEFAULT 0,
                        work_order TEXT)''')

    count = 0
    try:
        with open(CSV_FILE, mode='r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            # Skip header if your Excel has one (e.g., "IP", "Name", "Loc")
            next(reader, None) 
            
            for row in reader:
                if len(row) < 3: continue # Skip empty or broken rows
                
                ip, name, loc = row[0].strip(), row[1].strip(), row[2].strip()
                
                # INSERT OR IGNORE: This prevents errors if an IP already exists
                cursor.execute('''INSERT OR IGNORE INTO cameras (ip, name, location) 
                                 VALUES (?, ?, ?)''', (ip, name, loc))
                count += 1
        
        conn.commit()
        print(f"✅ SUCCESS: {count} cameras have been loaded into the database.")
        
    except Exception as e:
        print(f"⚠️ Error during import: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    import_from_csv()
