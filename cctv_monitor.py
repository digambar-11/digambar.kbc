import subprocess, platform, time, requests, sqlite3, os, smtplib, threading, csv
import tkinter as tk
from tkinter import simpledialog, messagebox
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from concurrent.futures import ThreadPoolExecutor

# --- 1. CONFIGURATION ---
TELE_TOKEN = "8679608431:AAGxbwri7v7UaP0J1-ooFQMPU_k0B5cUZyQ"
CHAT_ID_CCTV = "5003052243"
DB_NAME = "cctv_manager.db"
LOG_FILE = "downtime_report.csv"  # Permanent Excel/CSV log
SMTP_SERVER, SMTP_PORT = "smtp.gmail.com", 587
EMAIL_SENDER, EMAIL_PASSWORD = "digambarkokitkar11@gmail.com", "tdmm fyde nxkt dcia" 
TO_EMAILS = ["digambarkokitkar11@gmail.com"]
CC_EMAILS = ["kokitkardigamber11@gmail.com"]

# --- 2. LOGGING SYSTEM (CSV/Excel) ---
def log_event(name, location, status, wo="N/A", comment="N/A"):
    """Appends status changes, WO, and comments to a permanent CSV file."""
    file_exists = os.path.isfile(LOG_FILE)
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    try:
        with open(LOG_FILE, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not file_exists:
                # Optimized header for your requirements
                writer.writerow(["Timestamp", "Camera Name", "Location", "Status", "Work Order", "Comment/Reason"])
            writer.writerow([timestamp, name, location, status, wo, comment])
    except Exception as e:
        print(f"⚠️ CSV Log Error: {e}")

# --- 3. QUEUE & DEADLINE SYSTEM ---
input_queue = [] 
is_ui_active = False
processed_count = 0 

def get_rolling_deadline(index):
    base_time = datetime.now().replace(hour=8, minute=30, second=0, microsecond=0)
    calculated = base_time + timedelta(minutes=(index * 5))
    hard_stop = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    return min(calculated, hard_stop)

def process_input_queue():
    global is_ui_active, processed_count
    while True:
        now = datetime.now()
        if now.hour >= 9:
            input_queue.clear()
            time.sleep(10)
            continue

        if input_queue and not is_ui_active:
            is_ui_active = True
            item = input_queue.pop(0) 
            cam_list = item if isinstance(item, list) else [item]
            names_str = "\n".join([f"• {c['name']} ({c['loc']})" for c in cam_list])
            
            current_deadline = get_rolling_deadline(processed_count)
            root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)

            if now < current_deadline:
                prompt = (f"INCIDENT #{processed_count + 1}\n"
                          f"Deadline: {current_deadline.strftime('%I:%M %p')}\n"
                          f"----------------------------\n{names_str}\n"
                          f"----------------------------\nENTER WO / REASON:")
                
                user_input = simpledialog.askstring("Brain Workflow Manager", prompt, parent=root)
                
                if datetime.now() >= current_deadline:
                    messagebox.showwarning("Expired", "Window closed. Use /mailit.")
                elif user_input:
                    for c in cam_list:
                        # Update DB with the input (Reason/WO)
                        query_db("UPDATE cameras SET work_order = ? WHERE ip = ?", (user_input, c['ip']), commit=True)
                        # Log manual entry to CSV
                        log_event(c['name'], c['loc'], "OFFLINE", wo="ASSIGNED", comment=user_input)
                
                processed_count += 1 
            else:
                messagebox.showinfo("Window Closed", "Entry window expired.")
            
            root.destroy(); is_ui_active = False
        time.sleep(1)

threading.Thread(target=process_input_queue, daemon=True).start()

# --- 4. DATABASE TOOLS ---
def query_db(query, params=(), commit=False):
    conn = sqlite3.connect(DB_NAME); cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        if commit: conn.commit()
        return cursor.fetchall()
    except Exception as e:
        print(f"🧠 DB Error: {e}"); return []
    finally: conn.close()

# --- 5. CORE FUNCTIONS ---
def is_online(ip):
    param = '-n' if platform.system().lower() == 'windows' else '-c'
    try:
        result = subprocess.run(['ping', param, '1', '-w', '1000', ip], 
                                capture_output=True, text=True, timeout=3, creationflags=0x08000000)
        return "TTL=" in result.stdout
    except: return False

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID_CCTV, "text": message, "parse_mode": "HTML"}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

def send_email_report(rows_html):
    subject = f"✅ NRC-1 CCTV Report: DAILY INCIDENT REPORT"
    total = query_db("SELECT COUNT(*) FROM cameras")[0][0]
    off = query_db("SELECT COUNT(*) FROM cameras WHERE status = 0")[0][0]
    on = total - off
    html = f"<html><body><h2>NRC-1 Dashboard</h2><p><b>{total}</b> Total | {on} Online | {off} Offline</p><table border='1' cellpadding='5'>{rows_html}</table></body></html>"
    try:
        msg = MIMEMultipart(); msg['From'] = EMAIL_SENDER; msg['To'] = ", ".join(TO_EMAILS)
        msg['Cc'] = ", ".join(CC_EMAILS); msg['Subject'] = subject; msg.attach(MIMEText(html, 'html'))
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT); server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD); server.sendmail(EMAIL_SENDER, TO_EMAILS + CC_EMAILS, msg.as_string()); server.quit()
        return True
    except: return False

# --- 6. MONITORING ENGINE ---
def run_monitor():
    camera_data = query_db("SELECT ip, name, location, status FROM cameras")
    ips = [row[0] for row in camera_data]
    
    with ThreadPoolExecutor(max_workers=100) as executor:
        results = list(executor.map(is_online, ips))
    
    hr = datetime.now().hour
    scan_batch_failures = [] 

    for i, (ip, name, loc, old_status) in enumerate(camera_data):
        new_status = 1 if results[i] else 0
        if new_status != old_status:
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            query_db("UPDATE cameras SET status = ?, last_change = ? WHERE ip = ?", (new_status, ts, ip), commit=True)
            
            if new_status == 0:
                # Log the offline event
                log_event(name, loc, "OFFLINE", wo="PENDING", comment="System Detected")
                query_db("UPDATE cameras SET is_pending = 1 WHERE ip = ?", (ip,), commit=True)
                send_telegram(f"🔴 <b>OFFLINE:</b> <code>{name}</code>")
                if 4 <= hr < 9:
                    scan_batch_failures.append({'ip': ip, 'name': name, 'loc': loc})
            
            elif new_status == 1:
                # RECOVERY LOGGING: Fetch the reason from the database
                stored_wo = query_db("SELECT work_order FROM cameras WHERE ip = ?", (ip,))
                reason = stored_wo[0][0] if stored_wo and stored_wo[0][0] else "Manual Recovery"
                
                log_event(name, loc, "RECOVERED", wo=reason, comment="Connection Restored")
                send_telegram(f"🟢 <b>STABLE:</b> <code>{name}</code>")

    if scan_batch_failures:
        input_queue.append(scan_batch_failures if len(scan_batch_failures) > 1 else scan_batch_failures[0])

def check_schedule_and_commands():
    now = datetime.now()
    try:
        resp = requests.get(f"https://api.telegram.org/bot{TELE_TOKEN}/getUpdates", params={"offset": -1}, timeout=5).json()
        if resp["result"]:
            cmd = resp["result"][-1].get("message", {}).get("text", "").strip().lower()
            if cmd == "/mailit":
                missing = query_db("SELECT ip, name, location FROM cameras WHERE (status = 0 OR is_pending = 1) AND (work_order IS NULL OR work_order = '')")
                if missing:
                    input_queue.append([{'ip': i, 'name': n, 'loc': l} for i, n, l in missing])
                    send_telegram("🔍 Manual Audit triggered on PC.")
            elif cmd == "/status":
                total = query_db("SELECT COUNT(*) FROM cameras")[0][0]
                off = query_db("SELECT COUNT(*) FROM cameras WHERE status = 0")[0][0]
                send_telegram(f"📊 Total: {total} | 🔴 Offline: {off}")
    except: pass

    if now.hour == 9 and now.minute == 0:
        incidents = query_db("SELECT name, location, status, work_order FROM cameras WHERE status = 0 OR is_pending = 1")
        if incidents:
            rows_html = "".join([f"<tr><td>{n}</td><td>{l}</td><td><b style='color:{'red' if s==0 else 'green'}'>{'OFFLINE' if s==0 else 'RECOVERED'}</b> (WO: {w})</td></tr>" for n, l, s, w in incidents])
            if send_email_report(rows_html):
                send_telegram("📧 <b>9 AM Report Sent.</b>")
                query_db("UPDATE cameras SET is_pending = 0, work_order = NULL WHERE status = 1", commit=True)
                global processed_count
                processed_count = 0 

# --- 7. EXECUTION ---
if __name__ == "__main__":
    print(f"🚀 SYSTEM RUNNING. Logging to: {LOG_FILE}")
    time.sleep(60)
    while True:
        try:
            run_monitor()
            check_schedule_and_commands()
            time.sleep(40)
        except Exception as e:
            time.sleep(30)
