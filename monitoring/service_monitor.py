# Giám sát các services và mạng
#!/usr/bin/env python3
import time
import socket
import logging
import requests
import psutil
import json
import os
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

WEBHOOK_URL = os.getenv("AI_AGENT_WEBHOOK_URL", "http://localhost:8000/webhook")
HOSTNAME    = socket.gethostname()

# ─────────────────────────────────────────────
# NGƯỠNG CẢNH BÁO NETWORK
# Chỉnh các giá trị này theo môi trường thực tế
# ─────────────────────────────────────────────
NETWORK_THRESHOLDS = {
    "packet_drop_rate":   0.01,   # 1%  tổng packets bị drop → CRITICAL
    "error_rate":         0.01,   # 1%  tổng packets bị lỗi  → CRITICAL
    "tcp_time_wait_max":  500,    # Quá nhiều TIME_WAIT       → WARNING
    "tcp_close_wait_max": 100,    # Quá nhiều CLOSE_WAIT      → CRITICAL
}


# ─────────────────────────────────────────────
# PORT CHECKER (giữ nguyên từ trước)
# ─────────────────────────────────────────────

class PortChecker:
    def __init__(self, services):
        self.services    = services
        self.port_status = {}   # Lưu trạng thái lần trước để chỉ alert khi DOWN mới

    def _is_port_open(self, host, port):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except:
            return False

    def check_all(self):
        """Trả về list alerts cho các port vừa chuyển từ UP → DOWN."""
        alerts = []
        for name, config in self.services.items():
            if not config.get('port'):
                continue
            is_open = self._is_port_open('127.0.0.1', config['port'])

            # Chỉ alert khi trạng thái chuyển UP → DOWN (tránh spam)
            if not is_open and self.port_status.get(name, True):
                alerts.append({
                    "alertname": "ServicePortDown",
                    "severity":  "critical",
                    "service":   name,
                    "message":   f"🚨 {name} (Port {config['port']}) is DOWN!",
                    "metric":    f"port={config['port']}"
                })
            self.port_status[name] = is_open
        return alerts


# ─────────────────────────────────────────────
# NETWORK CHECKER (mới hoàn toàn)
# ─────────────────────────────────────────────

class NetworkChecker:
    """
    Giám sát network metrics bằng cách so sánh delta giữa 2 lần đo liên tiếp.
    Tại sao dùng delta? Vì bytes_sent/recv là counter tích lũy từ lúc boot —
    chỉ sự thay đổi trong khoảng check_interval mới phản ánh tình trạng hiện tại.
    """

    def __init__(self):
        # Snapshot lần trước — khởi tạo ngay khi start
        self._prev = psutil.net_io_counters()

    def check(self):
        """
        So sánh snapshot hiện tại với snapshot trước.
        Trả về list alerts nếu có chỉ số vượt ngưỡng, list rỗng nếu bình thường.
        """
        alerts  = []
        current = psutil.net_io_counters()
        prev    = self._prev

        # ── Kiểm tra counter reset (vd: do reboot) ──────────────────────────
        if current.packets_sent < prev.packets_sent or current.packets_recv < prev.packets_recv:
            logger.info("🔄 Network counters reset detected (reboot?). Resetting baseline.")
            self._prev = current
            return []

        # ── Tính delta ────────────────────────────────────────────────────────
        d_pkts_sent = max(current.packets_sent - prev.packets_sent, 1)  # tránh chia 0
        d_pkts_recv = max(current.packets_recv - prev.packets_recv, 1)
        d_errin     = current.errin   - prev.errin
        d_errout    = current.errout  - prev.errout
        d_dropin    = current.dropin  - prev.dropin
        d_dropout   = current.dropout - prev.dropout

        total_pkts  = d_pkts_sent + d_pkts_recv

        # ── Kiểm tra packet drop rate ─────────────────────────────────────────
        drop_rate = (d_dropin + d_dropout) / total_pkts
        if drop_rate > NETWORK_THRESHOLDS["packet_drop_rate"]:
            alerts.append({
                "alertname": "NetworkHighPacketDropRate",
                "severity":  "critical",
                "service":   "network",
                "message": (
                    f"⚠️ Packet drop rate cao: {drop_rate:.2%} "
                    f"(dropin={d_dropin}, dropout={d_dropout} trong {total_pkts} packets)"
                ),
                "metric": f"drop_rate={drop_rate:.6f}"
            })

        # ── Kiểm tra error rate ───────────────────────────────────────────────
        error_rate = (d_errin + d_errout) / total_pkts
        if error_rate > NETWORK_THRESHOLDS["error_rate"]:
            alerts.append({
                "alertname": "NetworkHighErrorRate",
                "severity":  "critical",
                "service":   "network",
                "message": (
                    f"⚠️ Network error rate cao: {error_rate:.2%} "
                    f"(errin={d_errin}, errout={d_errout})"
                ),
                "metric": f"error_rate={error_rate:.6f}"
            })

        # ── Kiểm tra TCP connection states ────────────────────────────────────
        try:
            conns            = psutil.net_connections()
            time_wait_count  = sum(1 for c in conns if c.status == 'TIME_WAIT')
            close_wait_count = sum(1 for c in conns if c.status == 'CLOSE_WAIT')

            if time_wait_count > NETWORK_THRESHOLDS["tcp_time_wait_max"]:
                alerts.append({
                    "alertname": "NetworkTCPTimeWaitHigh",
                    "severity":  "warning",
                    "service":   "network",
                    "message":   f"⚠️ Quá nhiều TCP TIME_WAIT: {time_wait_count} connections",
                    "metric":    f"time_wait={time_wait_count}"
                })

            if close_wait_count > NETWORK_THRESHOLDS["tcp_close_wait_max"]:
                alerts.append({
                    "alertname": "NetworkTCPCloseWaitHigh",
                    "severity":  "critical",
                    "service":   "network",
                    "message":   f"🚨 Quá nhiều TCP CLOSE_WAIT: {close_wait_count} connections — app không đóng socket đúng cách",
                    "metric":    f"close_wait={close_wait_count}"
                })

        except psutil.AccessDenied:
            logger.warning("⚠️ Không đủ quyền đọc TCP connections — chạy với sudo để enable tính năng này")

        # Cập nhật snapshot cho lần check tiếp theo
        self._prev = current
        return alerts


# ─────────────────────────────────────────────
# UNIFIED MONITOR
# ─────────────────────────────────────────────

class UnifiedServiceMonitor:
    def __init__(self):
        # Load linh động từ services_config.json
        config_path = os.path.join(os.path.dirname(__file__), "..", "config", "services_config.json")
        self.services = {}
        self.alert_cooldown = 60  # Default cooldown
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                full_config = json.load(f)
                services_config = full_config.get("services", {})
                self.alert_cooldown = full_config.get("monitoring", {}).get("alert_cooldown", 60)
                for name, config in services_config.items():
                    # Chỉ giám sát nếu enabled=True và có khai báo port
                    if config.get("enabled", False) and config.get("port"):
                        self.services[name] = {"port": config["port"]}
            logger.info(f"📂 Loaded {len(self.services)} services from config (cooldown={self.alert_cooldown}s)")
        except Exception as e:
            logger.error(f"❌ Failed to load services_config.json: {e}")
            # Fallback nếu lỗi file
            self.services = {"nginx": {"port": 80}, "postgresql": {"port": 5432}}

        self.port_checker    = PortChecker(self.services)
        self.network_checker = NetworkChecker()
        self.alert_last_sent = {}  # { "alertname": timestamp }
        logger.info(f"🚀 Unified Monitor started on {HOSTNAME}")
        logger.info(f"   Monitoring ports: { {k: v['port'] for k, v in self.services.items()} }")
        logger.info(f"   Network thresholds: {NETWORK_THRESHOLDS}")

    def _send_to_webhook(self, alert_data: dict):
        """Gửi alert lên /webhook theo chuẩn Alertmanager payload."""
        alert_name = alert_data.get("alertname", "UnknownAlert")
        service    = alert_data.get("service", "unknown")
        
        # Cooldown key should be unique per alert type AND service
        cooldown_key = f"{alert_name}_{service}"
        
        # Kiểm tra cooldown
        now = time.time()
        if cooldown_key in self.alert_last_sent:
            if now - self.alert_last_sent[cooldown_key] < self.alert_cooldown:
                logger.debug(f"⏳ Skipping alert {cooldown_key} (cooldown active)")
                return

        payload = {
            "status": "firing",
            "alerts": [{
                "status": "firing",
                "labels": {
                    "alertname": alert_name,
                    "severity":  alert_data.get("severity", "critical"),
                    "instance":  HOSTNAME,
                    "service":   service,
                },
                "annotations": {
                    "summary":     alert_data.get("message", ""),
                    "description": alert_data.get("metric", "")
                },
                "startsAt":     datetime.utcnow().isoformat() + 'Z',
                "generatorURL": f"http://{HOSTNAME}/monitor"
            }]
        }
        try:
            r = requests.post(WEBHOOK_URL, json=payload, timeout=5)
            if r.status_code == 200:
                self.alert_last_sent[cooldown_key] = now
                logger.info(f"✅ Alert sent: {cooldown_key} → HTTP {r.status_code}")
        except Exception as e:
            logger.error(f"❌ Webhook failed: {e}")

    def run(self):
        logger.info("📡 Monitoring loop started — check interval: 10s")
        while True:
            try:
                # ── Port check ───────────────────────────────────────────────
                for alert in self.port_checker.check_all():
                    logger.warning(f"PORT ALERT: {alert['message']}")
                    self._send_to_webhook(alert)

                # ── Network check ────────────────────────────────────────────
                for alert in self.network_checker.check():
                    logger.warning(f"NETWORK ALERT: {alert['message']}")
                    self._send_to_webhook(alert)

            except Exception as e:
                logger.error(f"Monitor loop error: {e}")

            time.sleep(10)


if __name__ == "__main__":
    monitor = UnifiedServiceMonitor()
    monitor.run()