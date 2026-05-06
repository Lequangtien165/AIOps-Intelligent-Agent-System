#!/bin/bash
# Docker entrypoint - start monitoring components as sidecars and then run the main command

set -e

# Đảm bảo PYTHONPATH trỏ tới gốc để các module tìm thấy nhau
export PYTHONPATH=$PYTHONPATH:/app

# Tạo sẵn các file log để bộ monitor không bị crash
mkdir -p /var/log/nginx
touch /var/log/syslog /var/log/nginx/error.log /tmp/test_syslog.log

echo "🚀 Starting AIOps Sidecars..."
echo "   • monitoring/log_watcher.py"
echo "   • monitoring/service_monitor.py"

# Start log_watcher in background
python3 monitoring/log_watcher.py > /dev/stdout 2>&1 &
LOG_WATCHER_PID=$!

# Start service_monitor in background
python3 monitoring/service_monitor.py > /dev/stdout 2>&1 &
SERVICE_MONITOR_PID=$!

# Cleanup on exit
trap "kill $LOG_WATCHER_PID $SERVICE_MONITOR_PID" EXIT

echo "🌐 Executing main command: $@"
exec "$@"
