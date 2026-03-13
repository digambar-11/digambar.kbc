import os
import shutil
import time
from datetime import datetime

# --- CONFIGURATION ---
# Updated to match your actual filename
DB_NAME = "cctv_manager.db" 
BACKUP_FOLDER = "Backups"
LOG_FILE = "backup_status.log"
RETENTION_DAYS = 15

def write_log(message):
    """Saves backup status to a text file for history."""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")
    print(message)

def run_daily_backup():
    # Ensure backup directory exists
    if not os.path.exists(BACKUP_FOLDER):
        os.makedirs(BACKUP_FOLDER)

    write_log("🛡️ Independent Backup Engine started. System: STANDBY.")
    
    while True:
        now = datetime.now()
        
        # ⏰ TRIGGER TIME: 11:30 PM (23:30)
        if now.hour == 23 and now.minute == 30:
            ts = now.strftime("%Y-%m-%d")
            backup_path = os.path.join(BACKUP_FOLDER, f"backup_{ts}.db")
            
            try:
                if os.path.exists(DB_NAME):
                    # shutil.copy2 preserves original file metadata (timestamps)
                    shutil.copy2(DB_NAME, backup_path)
                    write_log(f"✅ SUCCESS: Database backed up to {backup_path}")
                else:
                    write_log(f"⚠️ ERROR: {DB_NAME} not found. Check filename.")

                # --- HOUSEKEEPING: Delete files older than 15 days ---
                current_time = time.time()
                for f in os.listdir(BACKUP_FOLDER):
                    f_path = os.path.join(BACKUP_FOLDER, f)
                    if os.path.isfile(f_path):
                        # Convert age to days
                        age_days = (current_time - os.path.getmtime(f_path)) / 86400
                        if age_days > RETENTION_DAYS:
                            os.remove(f_path)
                            write_log(f"🧹 CLEANUP: Removed old backup file: {f}")
                            
            except Exception as e:
                write_log(f"❌ CRITICAL ERROR during backup: {str(e)}")
            
            # Wait 70 seconds so we don't trigger again in the same minute
            time.sleep(70)
        
        # Check the clock every 30 seconds
        time.sleep(30)

if __name__ == "__main__":
    run_daily_backup()
