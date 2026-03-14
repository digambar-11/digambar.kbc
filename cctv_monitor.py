import subprocess, platform, time, requests, sqlite3, os, smtplib, threading, csv, sys
import tkinter as tk
from tkinter import simpledialog, messagebox
import tkinter.scrolledtext as st 
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from concurrent.futures import ThreadPoolExecutor

# ==============================================================================
# CONFIGURATION
# ==============================================================================
IS_TRIAL = True              
TRIAL_START_DATE = "2026-03-15" 
TRIAL_DURATION_DAYS = 30     
AUTHORIZED_PC = "SECWRK1" 
MAX_LICENSED_DEVICES = 1000  

TELE_TOKEN = "8679608431:AAGxbwri7v7UaP0J1-ooFQMPU_k0B5cUZyQ"
CHAT_ID_CCTV = "5003052243"
DB_NAME = "cctv_manager.db"
LOG_FILE = "downtime_report.csv"
SMTP_SERVER, SMTP_PORT = "smtp.gmail.com", 587
EMAIL_SENDER, EMAIL_PASSWORD = "digambarkokitkar11@gmail.com", "tdmm fyde nxkt dcia" 
TO_EMAILS = ["digambarkokitkar11@gmail.com"]
CC_EMAILS = ["kokitkardigamber11@gmail.com"]

# --- NEW: STATUS NOTIFICATION HELPERS ---
def notify_startup():
    pc_name = platform.node()
    # Updated to match GUI style with the green circle and clear bold text
    msg = f"🟢 <b>Monitoring STARTED on {pc_name}</b>"
    update_gui_console(f"🟢 Monitoring STARTED on {pc_name}")
    send_telegram(msg)

def on_closing():
    """Handles proper shutdown notification when GUI is closed."""
    pc_name = platform.node()
    msg = f"⚠️ <b>SYSTEM OFFLINE:</b> Monitoring stopped on <b>{pc_name}</b>"
    send_telegram(msg)
    root_ui.destroy()
    sys.exit()

# --- UNIFIED LOGIC FUNCTION ---
def process_command_logic(cmd_raw, source="GUI"):
    """Handles both Telegram and GUI commands with the 4-9 window rule."""
    cmd_parts = cmd_raw.split(" ", 1)
    base_cmd = cmd_parts[0].lower()
    val = cmd_parts[1] if len(cmd_parts) > 1 else None
    hr = datetime.now().hour

    if base_cmd == "/status":
        off = query_db(f"SELECT COUNT(*) FROM cameras WHERE status = 0 LIMIT {MAX_LICENSED_DEVICES}")[0][0]
        msg = f"📊 Status Check: {off} Offline"
        if source == "GUI": update_gui_console(msg)
        send_telegram(msg)
        return

    if hr >= 9 or hr < 4:
        today_str = datetime.now().strftime('%Y-%m-%d')
        start_win = f"{today_str} 04:00:00"
        end_win = f"{today_str} 09:00:00"

        if base_cmd == "/wo":
            total_window_cams = query_db("SELECT name FROM cameras WHERE last_change BETWEEN ? AND ?", (start_win, end_win))
            if not total_window_cams:
                msg = "🤖 Bot: No offline cameras found in 4:00 AM to 9:00 AM window today."
                if source == "GUI": update_gui_console(msg)
                send_telegram(msg)
                return

            targets = query_db("SELECT name FROM cameras WHERE last_change BETWEEN ? AND ? AND (work_order IS NULL OR work_order = '')", (start_win, end_win))
            if not targets:
                msg = "🤖 Bot: All cameras from the 4-9 window already have Work Orders."
                if source == "GUI": update_gui_console(msg)
                send_telegram(msg)
            elif not val:
                names = ", ".join([t[0] for t in targets])
                msg = f"🤖 Bot: Found {len(targets)} camera(s) from 4-9 window needing WO: [{names}]\n👉 Use: /WO [number]"
                if source == "GUI": update_gui_console(msg)
                send_telegram(msg)
            else:
                query_db("UPDATE cameras SET work_order = ? WHERE last_change BETWEEN ? AND ? AND (work_order IS NULL OR work_order = '')", (val, start_win, end_win), commit=True)
                msg = f"✍️ WO {val} assigned to {len(targets)} window camera(s) via {source}."
                if source == "GUI": update_gui_console(msg)
                send_telegram(msg)
                check_and_trigger_report()

        elif base_cmd == "/comment":
            targets = query_db("SELECT name FROM cameras WHERE status = 1 AND last_change BETWEEN ? AND ? AND (work_order IS NULL OR work_order = '')", (start_win, end_win))
            if not targets:
                msg = "🤖 Bot: No recovered cameras from the 4-9 window require comments."
                if source == "GUI": update_gui_console(msg)
                send_telegram(msg)
            elif not val:
                names = ", ".join([t[0] for t in targets])
                msg = f"🤖 Bot: Found {len(targets)} recovered camera(s) from 4-9 window: [{names}]\n👉 Use: /comment [text]"
                if source == "GUI": update_gui_console(msg)
                send_telegram(msg)
            else:
                query_db("UPDATE cameras SET work_order = ? WHERE status = 1 AND last_change BETWEEN ? AND ? AND (work_order IS NULL OR work_order = '')", (val, start_win, end_win), commit=True)
                msg = f"💬 Comment saved via {source}."
                if source == "GUI": update_gui_console(msg)
                send_telegram(msg)
                check_and_trigger_report()

    elif 4 <= hr < 9:
        query_db("UPDATE cameras SET work_order = ? WHERE is_pending = 1", (cmd_raw,), commit=True)
        msg = f"📝 WO SAVED: {cmd_raw}"
        update_gui_console(msg)
        send_telegram(msg)

# --- GUI & TELEGRAM WRAPPERS ---
def handle_gui_command(event=None):
    cmd = cmd_entry.get().strip()
    cmd_entry.delete(0, tk.END)
    if cmd: process_command_logic(cmd, source="GUI")

def check_schedule_and_commands():
    now = datetime.now()
    try:
        resp = requests.get(f"https://api.telegram.org/bot{TELE_TOKEN}/getUpdates", params={"offset": -1}, timeout=5).json()
        if resp["result"]:
            last_msg = resp["result"][-1].get("message", {})
            cmd_text = last_msg.get("text", "").strip()
            msg_id = last_msg.get("message_id")
            if not hasattr(check_schedule_and_commands, "last_processed_id"):
                check_schedule_and_commands.last_processed_id = 0
            if msg_id > check_schedule_and_commands.last_processed_id:
                check_schedule_and_commands.last_processed_id = msg_id
                process_command_logic(cmd_text, source="TELEGRAM")
    except: pass
    if now.hour == 9 and now.minute == 0:
        run_final_mail_logic()

# ==============================================================================
# DATABASE & EMAIL
# ==============================================================================
def update_gui_console(text):
    if 'console_box' in globals():
        console_box.config(state='normal')
        ts = datetime.now().strftime('%H:%M:%S')
        tag = "info"
        if any(x in text.upper() for x in ["🔴", "OFFLINE", "❌", "STOPPED"]): tag = "error"
        if any(x in text.upper() for x in ["🟢", "STABLE", "STARTED"]): tag = "success"
        if any(x in text.upper() for x in ["🤖", "✍️", "📝", "💬", "📊"]): tag = "action"
        console_box.insert(tk.END, f"[{ts}] ", "time")
        console_box.insert(tk.END, f"{text}\n", tag)
        console_box.see(tk.END)
        console_box.config(state='disabled')

def check_and_trigger_report():
    off_count = query_db("SELECT COUNT(*) FROM cameras WHERE status = 0 AND is_pending = 1")[0][0]
    rec_count = query_db("SELECT COUNT(*) FROM cameras WHERE status = 1 AND is_pending = 1")[0][0]
    if off_count >= 1 and rec_count >= 1:
        run_final_mail_logic()

def run_final_mail_logic():
    incidents = query_db(f"SELECT name, location, status, work_order FROM cameras WHERE is_pending = 1")
    if incidents:
        rows = "".join([f"<tr><td style='border:1px solid #ddd; padding:8px;'>{n}</td><td style='border:1px solid #ddd; padding:8px;'>{l}</td><td style='border:1px solid #ddd; padding:8px;'>{'OFFLINE' if s==0 else 'RECOVERED'} (WO: {w})</td></tr>" for n,l,s,w in incidents])
        if send_email_report(rows):
            update_gui_console("✅ Email Sent Successfully.")
            query_db("UPDATE cameras SET is_pending = 0, work_order = NULL WHERE status = 1", commit=True)

def init_db():
    conn = sqlite3.connect(DB_NAME); cursor = conn.close()
    query_db('''CREATE TABLE IF NOT EXISTS cameras (
                ip TEXT PRIMARY KEY, name TEXT, location TEXT, 
                status INTEGER DEFAULT 1, last_change TEXT,
                is_pending INTEGER DEFAULT 0, work_order TEXT)''', commit=True)

def query_db(query, params=(), commit=False):
    conn = sqlite3.connect(DB_NAME); cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        if commit: conn.commit()
        return cursor.fetchall()
    except Exception as e: return []
    finally: conn.close()

def send_email_report(rows_html):
    subject = f"✅ NRC-1 CCTV Report: DAILY INCIDENT REPORT"
    total = query_db(f"SELECT COUNT(*) FROM cameras")[0][0]
    off = query_db(f"SELECT COUNT(*) FROM cameras WHERE status = 0")[0][0]
    on = total - off
    timestamp = datetime.now().strftime('%H:%M:%S')
    html = f"""<html><body style="font-family: Arial; padding: 20px;">
        <div style="max-width: 800px; margin: auto; background: #fff; padding: 20px; border: 1px solid #ddd;">
            <h2>NRC-1 CCTV Status Dashboard</h2>
            <p>Incident Report at {timestamp}</p>
            <div style="display: flex; text-align: center; margin-bottom: 20px;">
                <div style="flex:1; border:1px solid #ddd; padding:10px;"><b>{total}</b><br>Total</div>
                <div style="flex:1; border:1px solid #ddd; border-top:4px solid #27ae60; padding:10px;"><b>{on}</b><br>Online</div>
                <div style="flex:1; border:1px solid #ddd; border-top:4px solid #e74c3c; padding:10px;"><b>{off}</b><br>Offline</div>
            </div>
            <table width="100%" style="border-collapse: collapse;">
                <tr style="background: #5dade2; color: white;"><th>Asset</th><th>Location</th><th>Status</th></tr>
                {rows_html}
            </table>
        </div></body></html>"""
    try:
        msg = MIMEMultipart(); msg['From'] = EMAIL_SENDER; msg['To'] = ", ".join(TO_EMAILS)
        msg['Cc'] = ", ".join(CC_EMAILS); msg['Subject'] = subject; msg.attach(MIMEText(html, 'html'))
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT); server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD); server.sendmail(EMAIL_SENDER, TO_EMAILS + CC_EMAILS, msg.as_string()); server.quit()
        return True
    except: return False

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
    camera_data = query_db(f"SELECT ip, name, location, status FROM cameras")
    ips = [row[0] for row in camera_data]
    with ThreadPoolExecutor(max_workers=100) as executor:
        results = list(executor.map(is_online, ips))
    for i, (ip, name, loc, old_status) in enumerate(camera_data):
        new_status = 1 if results[i] else 0
        if new_status != old_status:
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            query_db("UPDATE cameras SET status = ?, last_change = ? WHERE ip = ?", (new_status, ts, ip), commit=True)
            if new_status == 0:
                query_db("UPDATE cameras SET is_pending = 1 WHERE ip = ?", (ip,), commit=True)
                update_gui_console(f"🔴 OFFLINE: {name}") 
            else:
                update_gui_console(f"🟢 STABLE: {name}")

def start_monitoring_thread():
    # 1. Give GUI a moment to initialize
    time.sleep(1) 
    notify_startup() 
    
    # 2. Initial Status Check
    off_initial = query_db(f"SELECT COUNT(*) FROM cameras WHERE status = 0 LIMIT {MAX_LICENSED_DEVICES}")[0][0]
    msg_initial = f"📊 Initial Status Check: {off_initial} Offline"
    update_gui_console(msg_initial)
    send_telegram(msg_initial) # Copy of the GUI call for Telegram

    # 3. 10-Second delay for network initialization
    msg_wait = "⏳ Initializing network... Please wait 10s."
    update_gui_console(msg_wait)
    send_telegram(msg_wait) # Copy of the GUI call for Telegram
    
    time.sleep(10)
    
    # 4. Confirmation message after 10 seconds
    msg_ready = "🟢 Initialization Complete. Started live monitor..."
    update_gui_console(msg_ready)
    send_telegram(msg_ready) # Copy of the GUI call for Telegram

    while True:
        try:
            run_monitor()
            check_schedule_and_commands()
            time.sleep(40)
        except Exception as e:
            time.sleep(30)

if __name__ == "__main__":
    init_db()
    root_ui = tk.Tk()
    root_ui.title("NRC-1 CCTV MASTER CONSOLE")
    root_ui.geometry("650x570")
    
    # BIND THE CLOSE BUTTON
    root_ui.protocol("WM_DELETE_WINDOW", on_closing)
    
    console_box = st.ScrolledText(root_ui, width=75, height=22, bg="black", fg="white", font=("Consolas", 10))
    console_box.pack(padx=10, pady=10)
    console_box.tag_config("error", foreground="#ff4d4d"); console_box.tag_config("success", foreground="#2ecc71")
    console_box.tag_config("time", foreground="#888888"); console_box.tag_config("action", foreground="#f1c40f")
    console_box.config(state='disabled')
    
    cmd_frame = tk.Frame(root_ui); cmd_frame.pack(pady=5, fill='x', padx=20)
    cmd_entry = tk.Entry(cmd_frame, font=("Consolas", 11)); cmd_entry.pack(side='left', fill='x', expand=True, padx=10)
    cmd_entry.bind("<Return>", handle_gui_command)
    tk.Button(cmd_frame, text="SEND", command=handle_gui_command, bg="#34495e", fg="white").pack(side='right')
    
    threading.Thread(target=start_monitoring_thread, daemon=True).start()
    root_ui.mainloop()
