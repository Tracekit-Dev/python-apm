"""
TraceKit Metrics Buffer - Buffers and flushes metrics periodically
"""

from dataclasses import dataclass
from typing import Dict, List
import threading
import time
from tracekit.metrics_exporter import MetricsExporter


@dataclass
class MetricDataPoint:
    """Metric data point"""
    name: str
    tags: Dict[str, str]
    value: float
    timestamp: float  # Unix timestamp in seconds
    metric_type: str  # 'counter', 'gauge', or 'histogram'


class MetricsBuffer:
    """MetricsBuffer collects metrics and flushes them periodically"""

    def __init__(self, endpoint: str, api_key: str, service_name: str):
        self.data: List[MetricDataPoint] = []
        self.exporter = MetricsExporter(endpoint, api_key, service_name)
        self._lock = threading.Lock()
        self._flush_thread: threading.Thread = None
        self._shutdown = False
        self.max_size = 100
        self.flush_interval = 10.0  # 10 seconds

    def start(self) -> None:
        """Start periodic flushing"""
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()

    def add(self, data_point: MetricDataPoint) -> None:
        """Add a metric data point"""
        if self._shutdown:
            return

        with self._lock:
            self.data.append(data_point)
            should_flush = len(self.data) >= self.max_size

        # Flush immediately if buffer is full
        if should_flush:
            self._flush()

    def _flush_loop(self) -> None:
        """Background thread that flushes periodically"""
        while not self._shutdown:
            time.sleep(self.flush_interval)
            if not self._shutdown:
                self._flush()

    def _flush(self) -> None:
        """Flush buffered metrics"""
        with self._lock:
            if not self.data:
                return

            to_export = self.data
            self.data = []

        try:
            self.exporter.export(to_export)
        except Exception as e:
            # Log error but don't crash
            print(f"Failed to export metrics: {e}")

    def shutdown(self) -> None:
        """Shutdown buffer and flush remaining metrics"""
        self._shutdown = True

        # Wait for flush thread to finish
        if self._flush_thread and self._flush_thread.is_alive():
            self._flush_thread.join(timeout=2.0)

        # Final flush
        self._flush()
