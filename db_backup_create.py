import os
import shutil
import time
from datetime import datetime

# --- CONFIGURATION ---
DB_NAME = "cctv_manager.db"
BACKUP_FOLDER = "Backups"
LOG_FILE = "backup_status.log"
RETENTION_DAYS = 15  # days

def write_log(message: str) -> None:
    """Append backup status to a log file and print it."""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{timestamp}] {message}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        # If logging fails, at least print to stdout
        print("⚠️ Failed to write to log file.")
    print(message)

def perform_backup() -> None:
    """Perform one backup run and cleanup old backups."""
    # Ensure backup directory exists
    os.makedirs(BACKUP_FOLDER, exist_ok=True)

    now = datetime.now()
    ts = now.strftime("%Y-%m-%d")
    backup_path = os.path.join(BACKUP_FOLDER, f"backup_{ts}.db")

    try:
        if os.path.exists(DB_NAME):
            # shutil.copy2 preserves timestamps/metadata
            shutil.copy2(DB_NAME, backup_path)
            write_log(f"✅ SUCCESS: Database backed up to {backup_path}")
        else:
            write_log(f"⚠️ ERROR: {DB_NAME} not found. Check filename/path.")

        # --- HOUSEKEEPING: Delete files older than RETENTION_DAYS ---
        current_time = time.time()
        try:
            for fname in os.listdir(BACKUP_FOLDER):
                f_path = os.path.join(BACKUP_FOLDER, fname)
                if os.path.isfile(f_path):
                    age_days = (current_time - os.path.getmtime(f_path)) / 86400
                    if age_days > RETENTION_DAYS:
                        os.remove(f_path)
                        write_log(f"🧹 CLEANUP: Removed old backup file: {fname}")
        except Exception as e:
            write_log(f"⚠️ Housekeeping error: {e}")

    except Exception as e:
        write_log(f"❌ CRITICAL ERROR during backup: {e}")

def run_daily_backup() -> None:
    """Main loop: run backup once per day at 23:30."""
    write_log("🛡️ Independent Backup Engine started. System: STANDBY.")

    while True:
        now = datetime.now()

        # ⏰ TRIGGER TIME: 11:30 PM (23:30)
        if now.hour == 23 and now.minute == 30:
            perform_backup()
            # Wait 70 seconds so we don't trigger again in the same minute
            time.sleep(70)

        # Check the clock every 30 seconds
        time.sleep(30)

if __name__ == "__main__":
    run_daily_backup()
