import subprocess, platform, time, requests, sqlite3, os, smtplib, threading, csv, sys
import tkinter as tk
from tkinter import simpledialog, messagebox
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from concurrent.futures import ThreadPoolExecutor

# ==============================================================================
# PERFORMANCE & LICENSE CONFIGURATION
# ==============================================================================
IS_TRIAL = True              # Set to False for the Paid Version
TRIAL_START_DATE = "2026-03-15" 
TRIAL_DURATION_DAYS = 30     

# HARDWARE LOCKING: Set to customer's PC Name (e.g., platform.node())
AUTHORIZED_PC = "OFFICE-PC-01" 

# SCALE CONTROL
MAX_LICENSED_DEVICES = 500   
# ==============================================================================

# --- 1. CONFIGURATION ---
TELE_TOKEN = "8679608431:AAGxbwri7v7UaP0J1-ooFQMPU_k0B5cUZyQ"
CHAT_ID_CCTV = "5003052243"
DB_NAME = "cctv_manager.db"
LOG_FILE = "downtime_report.csv"
SMTP_SERVER, SMTP_PORT = "smtp.gmail.com", 587
EMAIL_SENDER, EMAIL_PASSWORD = "digambarkokitkar11@gmail.com", "tdmm fyde nxkt dcia" 
TO_EMAILS = ["digambarkokitkar11@gmail.com"]
CC_EMAILS = ["kokitkardigamber11@gmail.com"]

# --- 2. SECURITY GATEKEEPER ---
def check_gatekeepers():
    root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
    current_pc = platform.node()
    if AUTHORIZED_PC and current_pc != AUTHORIZED_PC:
        messagebox.showerror("Unauthorized Hardware", f"Licensed to: {AUTHORIZED_PC}\nCurrent PC: {current_pc}")
        root.destroy(); sys.exit()

    if IS_TRIAL:
        start_dt = datetime.strptime(TRIAL_START_DATE, "%Y-%m-%d")
        remaining = TRIAL_DURATION_DAYS - (datetime.now() - start_dt).days
        if remaining <= 0:
            messagebox.showerror("Trial Expired", "Please contact the provider."); root.destroy(); sys.exit()
        else:
            print(f"⏳ TRIAL ACTIVE: {remaining} days remaining.")
    root.destroy()

# --- 3. DATABASE INITIALIZATION & TOOLS ---
def init_db():
    """Ensures the database and table exist before the script pings anything."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS cameras (
                        ip TEXT PRIMARY KEY, 
                        name TEXT, 
                        location TEXT, 
                        status INTEGER DEFAULT 1, 
                        last_change TEXT,
                        is_pending INTEGER DEFAULT 0,
                        work_order TEXT)''')
    conn.commit()
    conn.close()

def query_db(query, params=(), commit=False):
    conn = sqlite3.connect(DB_NAME); cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        if commit: conn.commit()
        return cursor.fetchall()
    except Exception as e:
        print(f"🧠 DB Error: {e}"); return []
    finally: conn.close()

# --- 4. LOGGING & EMAILS ---
def log_event(name, location, status, wo="N/A", comment="N/A"):
    file_exists = os.path.isfile(LOG_FILE)
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        with open(LOG_FILE, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["Timestamp", "Camera Name", "Location", "Status", "Work Order", "Comment/Reason"])
            writer.writerow([ts, name, location, status, wo, comment])
    except: pass

def send_email_report(rows_html):
    """Generates and sends the professional dashboard email report."""
    subject = f"✅ NRC-1 CCTV Report: DAILY INCIDENT REPORT"
    
    # Accurate counts for the dashboard header
    total = query_db(f"SELECT COUNT(*) FROM (SELECT 1 FROM cameras LIMIT {MAX_LICENSED_DEVICES})")[0][0]
    off = query_db(f"SELECT COUNT(*) FROM (SELECT 1 FROM cameras WHERE status = 0 LIMIT {MAX_LICENSED_DEVICES})")[0][0]
    on = total - off
    timestamp = datetime.now().strftime('%H:%M:%S')

    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; background-color: #f4f7f6; padding: 20px;">
        <div style="max-width: 800px; margin: auto; background-color: #ffffff; padding: 30px; border-radius: 10px; border: 1px solid #e0e0e0;">
            <h2 style="color: #2c3e50; margin-bottom: 5px;">NRC-1 CCTV Status Dashboard</h2>
            <p style="color: #7f8c8d; font-size: 14px; margin-bottom: 25px;">System Incident detected at {timestamp}</p>
            
            <div style="display: flex; gap: 10px; margin-bottom: 30px; text-align: center;">
                <div style="flex: 1; padding: 15px; background: #f9f9f9; border: 1px solid #ddd; border-radius: 8px;">
                    <span style="font-size: 12px; color: #7f8c8d; text-transform: uppercase;">Total Units</span><br>
                    <b style="font-size: 24px; color: #2c3e50;">{total}</b>
                </div>
                <div style="flex: 1; padding: 15px; background: #f9f9f9; border: 1px solid #ddd; border-top: 4px solid #27ae60; border-radius: 8px;">
                    <span style="font-size: 12px; color: #7f8c8d; text-transform: uppercase;">Online</span><br>
                    <b style="font-size: 24px; color: #27ae60;">{on}</b>
                </div>
                <div style="flex: 1; padding: 15px; background: #f9f9f9; border: 1px solid #ddd; border-top: 4px solid #e74c3c; border-radius: 8px;">
                    <span style="font-size: 12px; color: #7f8c8d; text-transform: uppercase;">Offline</span><br>
                    <b style="font-size: 24px; color: #e74c3c;">{off:02d}</b>
                </div>
            </div>

            <h4 style="color: #2c3e50; border-bottom: 2px solid #eee; padding-bottom: 10px;">Incident Details:</h4>
            
            <table width="100%" cellpadding="10" cellspacing="0" style="border-collapse: collapse; font-size: 13px;">
                <thead>
                    <tr style="background-color: #5dade2; color: white; text-align: left;">
                        <th style="border: 1px solid #5dade2;">Asset Location</th>
                        <th style="border: 1px solid #5dade2;">Camera Asset #</th>
                        <th style="border: 1px solid #5dade2;">Area</th>
                        <th style="border: 1px solid #5dade2;">Status</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>

            <div style="margin-top: 30px; padding-top: 15px; border-top: 1px solid #eee; font-size: 11px; color: #bdc3c7;">
                <b>NRC-1 Automation Bot</b> | Site Location: Ras Alsheikh Hamid
            </div>
        </div>
    </body>
    </html>
    """

    try:
        msg = MIMEMultipart(); msg['From'] = EMAIL_SENDER; msg['To'] = ", ".join(TO_EMAILS)
        msg['Cc'] = ", ".join(CC_EMAILS); msg['Subject'] = subject; msg.attach(MIMEText(html, 'html'))
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT); server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD); server.sendmail(EMAIL_SENDER, TO_EMAILS + CC_EMAILS, msg.as_string()); server.quit()
        return True
    except Exception as e:
        print(f"📧 Dashboard Email Fail: {e}")
        return False

# --- 5. QUEUE SYSTEM ---
input_queue = []; is_ui_active = False; processed_count = 0 

def get_rolling_deadline(index):
    base = datetime.now().replace(hour=8, minute=30, second=0, microsecond=0)
    return min(base + timedelta(minutes=(index * 5)), datetime.now().replace(hour=9, minute=0, second=0))

def process_input_queue():
    global is_ui_active, processed_count
    while True:
        if datetime.now().hour >= 9:
            input_queue.clear(); time.sleep(10); continue
        if input_queue and not is_ui_active:
            is_ui_active = True
            item = input_queue.pop(0)
            cam_list = item if isinstance(item, list) else [item]
            names_str = "\n".join([f"• {c['name']} ({c['loc']})" for c in cam_list])
            deadline = get_rolling_deadline(processed_count)
            root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
            if datetime.now() < deadline:
                prompt = f"INCIDENT #{processed_count+1}\nDeadline: {deadline.strftime('%I:%M %p')}\n{names_str}\nENTER WO/REASON:"
                val = simpledialog.askstring("Workflow", prompt, parent=root)
                if val:
                    for c in cam_list:
                        query_db("UPDATE cameras SET work_order = ? WHERE ip = ?", (val, c['ip']), commit=True)
                        log_event(c['name'], c['loc'], "OFFLINE", wo="ASSIGNED", comment=val)
                processed_count += 1
            root.destroy(); is_ui_active = False
        time.sleep(1)

threading.Thread(target=process_input_queue, daemon=True).start()

# --- 6. CORE ENGINE ---
def is_online(ip):
    param = '-n' if platform.system().lower() == 'windows' else '-c'
    try:
        res = subprocess.run(['ping', param, '1', '-w', '1000', ip], capture_output=True, text=True, timeout=3, creationflags=0x08000000)
        return "TTL=" in res.stdout
    except: return False

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
    try: requests.post(url, json={"chat_id": CHAT_ID_CCTV, "text": message, "parse_mode": "HTML"}, timeout=10)
    except: pass

def run_monitor():
    camera_data = query_db(f"SELECT ip, name, location, status FROM cameras LIMIT {MAX_LICENSED_DEVICES}")
    ips = [row[0] for row in camera_data]
    with ThreadPoolExecutor(max_workers=100) as executor:
        results = list(executor.map(is_online, ips))
    
    hr = datetime.now().hour
    batch_fails = []
    for i, (ip, name, loc, old_status) in enumerate(camera_data):
        new_status = 1 if results[i] else 0
        if new_status != old_status:
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            query_db("UPDATE cameras SET status = ?, last_change = ? WHERE ip = ?", (new_status, ts, ip), commit=True)
            if new_status == 0:
                log_event(name, loc, "OFFLINE", wo="PENDING")
                query_db("UPDATE cameras SET is_pending = 1 WHERE ip = ?", (ip,), commit=True)
                send_telegram(f"🔴 <b>OFFLINE:</b> <code>{name}</code>")
                if 4 <= hr < 9: batch_fails.append({'ip': ip, 'name': name, 'loc': loc})
            elif new_status == 1:
                log_event(name, loc, "RECOVERED")
                send_telegram(f"🟢 <b>STABLE:</b> <code>{name}</code>")
    if batch_fails: input_queue.append(batch_fails)

def check_schedule_and_commands():
    now = datetime.now()
    try:
        resp = requests.get(f"https://api.telegram.org/bot{TELE_TOKEN}/getUpdates", params={"offset": -1}, timeout=5).json()
        if resp["result"]:
            cmd = resp["result"][-1].get("message", {}).get("text", "").strip().lower()
            if cmd == "/status":
                off = query_db(f"SELECT COUNT(*) FROM cameras WHERE status = 0 LIMIT {MAX_LICENSED_DEVICES}")[0][0]
                trial_msg = ""
                if IS_TRIAL:
                    rem = TRIAL_DURATION_DAYS - (now - datetime.strptime(TRIAL_START_DATE, "%Y-%m-%d")).days
                    trial_msg = f"\n⏳ Trial Days: {rem}"
                send_telegram(f"📊 Licensed: {MAX_LICENSED_DEVICES} | 🔴 Offline: {off}{trial_msg}")
    except: pass

    if now.hour == 9 and now.minute == 0:
        incidents = query_db(f"SELECT name, location, status, work_order FROM cameras WHERE (status = 0 OR is_pending = 1) LIMIT {MAX_LICENSED_DEVICES}")
        if incidents:
            rows = "".join([f"<tr><td>{n}</td><td>{l}</td><td>{'OFFLINE' if s==0 else 'RECOVERED'} (WO: {w})</td></tr>" for n,l,s,w in incidents])
            if send_email_report(rows):
                query_db("UPDATE cameras SET is_pending = 0, work_order = NULL WHERE status = 1", commit=True)
                global processed_count; processed_count = 0

if __name__ == "__main__":
    init_db() # Create table if it doesn't exist
    check_gatekeepers()
    print(f"🚀 RUNNING | Limit: {MAX_LICENSED_DEVICES}")
    while True:
        try:
            run_monitor()
            check_schedule_and_commands()
            time.sleep(40)
        except Exception as e:
            time.sleep(30)
