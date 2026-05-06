# Giám sát Log thời gian thực bằng Watchdog và gửi Alert về AI Agent.
import os
import time
import requests
import json
import socket
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# --- CẤU HÌNH ---
ENV_LOG_FILES = os.getenv("WATCH_LOG_FILES")
if ENV_LOG_FILES:
    LOG_FILES = [f.strip() for f in ENV_LOG_FILES.split(",")]
else:
    LOG_FILES = ["/var/log/syslog", "/var/log/nginx/error.log", "/tmp/test_syslog.log"]

WEBHOOK_URL = os.getenv("AI_AGENT_WEBHOOK_URL", "http://localhost:8000/webhook")
ERROR_KEYWORDS = ["ERROR", "CRITICAL", "FATAL", "EXCEPTION", "FAILED", "PANIC"]
ALERT_COOLDOWN = int(os.getenv("ALERT_COOLDOWN", "60"))
HOSTNAME = socket.gethostname()

last_alerts = {}

def send_alert_to_ai_agent(log_line, file_path):
    now = time.time()
    if file_path in last_alerts and now - last_alerts[file_path] < ALERT_COOLDOWN:
        return

    timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    payload = {
        "receiver": "log-watcher",
        "status": "firing",
        "alerts": [{
            "status": "firing",
            "labels": {
                "alertname": "LogFileErrorDetected",
                "severity": "critical",
                "instance": HOSTNAME,
                "service": "log-monitoring",
                "source_file": file_path
            },
            "annotations": {
                "summary": f"Phát hiện lỗi trong file log: {file_path}",
                "description": log_line.strip()
            },
            "startsAt": timestamp,
            "generatorURL": f"http://{HOSTNAME}/log-watcher"
        }]
    }

    try:
        response = requests.post(WEBHOOK_URL, json=payload, timeout=5)
        if response.status_code == 200:
            last_alerts[file_path] = now
            print(f"[{datetime.now()}] ✅ Alert sent for {file_path}")
    except Exception as e:
        print(f"❌ [{datetime.now()}] Webhook error: {e}")

class LogFileHandler(FileSystemEventHandler):
    def __init__(self, file_path):
        self.file_path = file_path
        self.file_handle = open(file_path, "r")
        self.file_handle.seek(0, os.SEEK_END)

    def on_modified(self, event):
        if event.src_path == self.file_path:
            # Handle log rotation or truncation
            current_pos = self.file_handle.tell()
            file_size = os.path.getsize(self.file_path)

            if file_size < current_pos:
                print(f"🔄 Log file {self.file_path} truncated or rotated. Resetting pointer to 0.")
                self.file_handle.seek(0)

            lines = self.file_handle.readlines()
            for line in lines:
                if any(k.upper() in line.upper() for k in ERROR_KEYWORDS):
                    print(f"🔥 Error detected in {self.file_path}: {line.strip()[:100]}...")
                    send_alert_to_ai_agent(line, self.file_path)

def watch_logs():
    print(f"🚀 Log Watcher (Watchdog-based) starting on {HOSTNAME}...")
    observer = Observer()
    handlers = []

    for path in LOG_FILES:
        if os.path.exists(path):
            folder = os.path.dirname(path)
            handler = LogFileHandler(path)
            observer.schedule(handler, folder, recursive=False)
            handlers.append(handler)
            print(f"👁️ Monitoring: {path}")
        else:
            print(f"⚠️ Warning: File not found: {path}")

    if not handlers:
        print("❌ No valid log files to monitor. Exiting.")
        return

    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    watch_logs()
