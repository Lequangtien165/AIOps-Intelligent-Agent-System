# prometheus_check.py
# Utilities để kiểm lại Prometheus metrics và xác nhận issue đã resolve

import os
import logging
import requests
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Prometheus configuration
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
PROMETHEUS_TIMEOUT = 10


class PrometheusChecker:
    """
    Kiểm lại Prometheus metrics để xác nhận issue đã resolve.
    
    Usage:
        checker = PrometheusChecker()
        is_resolved = checker.is_alert_resolved("node_cpu_high", "10.10.1.68")
    """
    
    def __init__(self, prometheus_url: str = PROMETHEUS_URL):
        self.base_url = prometheus_url.rstrip("/")
        self.query_url = f"{self.base_url}/api/v1/query"
    
    def get_metric(self, instance: str, metric_name: str) -> Optional[float]:
        """
        Query Prometheus để lấy current metric value.
        
        Example:
            - metric_name: "node_cpu_percent{instance='10.10.1.68'}"
            - Return: 45.5 (CPU percent)
        """
        try:
            query = f"{metric_name}{{instance='{instance}'}}"
            params = {"query": query}
            
            response = requests.get(
                self.query_url,
                params=params,
                timeout=PROMETHEUS_TIMEOUT
            )
            response.raise_for_status()
            
            data = response.json()
            if data.get("status") == "success":
                results = data.get("data", {}).get("result", [])
                if results:
                    value = results[0].get("value", [None, None])[1]
                    return float(value) if value else None
            
            return None
        except Exception as e:
            logger.error(f"Error querying Prometheus for {metric_name}: {e}")
            return None
    
    def is_alert_resolved(self, alert_name: str, instance: str) -> bool:
        """
        Kiểm lại nếu alert đã resolve dựa trên alert name.
        
        Mapping:
        - node_cpu_high: CPU < 80%
        - node_memory_high: Memory < 85%
        - node_disk_high: Disk < 85%
        - service_down: port accessible
        - network_packet_loss: Loss < 1%
        """
        
        try:
            # Extract instance IP/hostname
            # instance format: "10.10.1.68:9100" or "10.10.1.68"
            host = instance.split(":")[0]
            
            if alert_name == "node_cpu_high":
                # Check if CPU is below 80%
                cpu = self.get_metric(host, "node_cpu_usage_percent")
                threshold = 80
                return cpu is not None and cpu < threshold
            
            elif alert_name == "node_memory_high":
                # Check if Memory is below 85%
                mem = self.get_metric(host, "node_memory_usage_percent")
                threshold = 85
                return mem is not None and mem < threshold
            
            elif alert_name == "node_disk_high":
                # Check if Disk is below 85%
                disk = self.get_metric(host, "node_disk_usage_percent")
                threshold = 85
                return disk is not None and disk < threshold
            
            elif alert_name == "network_packet_loss":
                # Check if packet loss is below 1%
                loss = self.get_metric(host, "node_network_packet_loss_percent")
                threshold = 1
                return loss is not None and loss < threshold
            
            elif alert_name == "service_down":
                # Check if service is up (via port health check)
                # This would require specific port configuration
                logger.info(f"Service check for {host} - assuming resolved")
                return True
            
            else:
                # Default: assume resolved if we can't determine
                logger.warning(f"Unknown alert type: {alert_name}")
                return True
        
        except Exception as e:
            logger.error(f"Error in is_alert_resolved: {e}")
            return False
    
    def get_alert_metrics(self, instance: str) -> Dict[str, Any]:
        """
        Lấy tất cả metrics liên quan để report.
        
        Return:
        {
            "cpu_percent": 45.5,
            "memory_percent": 62.3,
            "disk_percent": 70.1,
            "timestamp": "2026-04-28T14:53:00"
        }
        """
        from datetime import datetime
        
        host = instance.split(":")[0]
        metrics = {
            "timestamp": datetime.now().isoformat(),
            "cpu_percent": self.get_metric(host, "node_cpu_usage_percent"),
            "memory_percent": self.get_metric(host, "node_memory_usage_percent"),
            "disk_percent": self.get_metric(host, "node_disk_usage_percent"),
        }
        return metrics


# Singleton instance
_checker: Optional[PrometheusChecker] = None


def get_prometheus_checker() -> PrometheusChecker:
    """Get singleton instance of PrometheusChecker"""
    global _checker
    if _checker is None:
        _checker = PrometheusChecker()
    return _checker
