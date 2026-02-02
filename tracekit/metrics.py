"""
TraceKit Metrics - Counter, Gauge, and Histogram implementations
"""

from abc import ABC, abstractmethod
from typing import Dict
from tracekit.metrics_buffer import MetricsBuffer, MetricDataPoint
import time
import threading


class Counter(ABC):
    """Counter tracks monotonically increasing values"""

    @abstractmethod
    def inc(self) -> None:
        """Increment counter by 1"""
        pass

    @abstractmethod
    def add(self, value: float) -> None:
        """Add value to counter"""
        pass


class Gauge(ABC):
    """Gauge tracks point-in-time values"""

    @abstractmethod
    def set(self, value: float) -> None:
        """Set gauge to value"""
        pass

    @abstractmethod
    def inc(self) -> None:
        """Increment gauge by 1"""
        pass

    @abstractmethod
    def dec(self) -> None:
        """Decrement gauge by 1"""
        pass


class Histogram(ABC):
    """Histogram tracks value distributions"""

    @abstractmethod
    def record(self, value: float) -> None:
        """Record a value"""
        pass


class CounterImpl(Counter):
    """Internal Counter implementation"""

    def __init__(self, name: str, tags: Dict[str, str], buffer: MetricsBuffer):
        self.name = name
        self.tags = tags
        self.buffer = buffer

    def inc(self) -> None:
        self.add(1.0)

    def add(self, value: float) -> None:
        if value < 0:
            return  # Counters must be monotonic

        self.buffer.add(MetricDataPoint(
            name=self.name,
            tags=self.tags,
            value=value,
            timestamp=time.time(),
            metric_type='counter'
        ))


class GaugeImpl(Gauge):
    """Internal Gauge implementation"""

    def __init__(self, name: str, tags: Dict[str, str], buffer: MetricsBuffer):
        self.name = name
        self.tags = tags
        self.buffer = buffer
        self._value = 0.0
        self._lock = threading.Lock()

    def set(self, value: float) -> None:
        with self._lock:
            self._value = value

        self.buffer.add(MetricDataPoint(
            name=self.name,
            tags=self.tags,
            value=value,
            timestamp=time.time(),
            metric_type='gauge'
        ))

    def inc(self) -> None:
        with self._lock:
            self._value += 1.0
            value = self._value

        self.buffer.add(MetricDataPoint(
            name=self.name,
            tags=self.tags,
            value=value,
            timestamp=time.time(),
            metric_type='gauge'
        ))

    def dec(self) -> None:
        with self._lock:
            self._value -= 1.0
            value = self._value

        self.buffer.add(MetricDataPoint(
            name=self.name,
            tags=self.tags,
            value=value,
            timestamp=time.time(),
            metric_type='gauge'
        ))


class HistogramImpl(Histogram):
    """Internal Histogram implementation"""

    def __init__(self, name: str, tags: Dict[str, str], buffer: MetricsBuffer):
        self.name = name
        self.tags = tags
        self.buffer = buffer

    def record(self, value: float) -> None:
        self.buffer.add(MetricDataPoint(
            name=self.name,
            tags=self.tags,
            value=value,
            timestamp=time.time(),
            metric_type='histogram'
        ))


class MetricsRegistry:
    """MetricsRegistry manages all metrics"""

    def __init__(self, endpoint: str, api_key: str, service_name: str):
        self.counters: Dict[str, CounterImpl] = {}
        self.gauges: Dict[str, GaugeImpl] = {}
        self.histograms: Dict[str, HistogramImpl] = {}
        self._lock = threading.Lock()
        self.buffer = MetricsBuffer(endpoint, api_key, service_name)
        self.buffer.start()

    def counter(self, name: str, tags: Dict[str, str] = None) -> Counter:
        """Get or create a counter"""
        if tags is None:
            tags = {}

        key = self._metric_key(name, tags)

        if key in self.counters:
            return self.counters[key]

        with self._lock:
            # Double-check after lock
            if key in self.counters:
                return self.counters[key]

            counter = CounterImpl(name, tags.copy(), self.buffer)
            self.counters[key] = counter
            return counter

    def gauge(self, name: str, tags: Dict[str, str] = None) -> Gauge:
        """Get or create a gauge"""
        if tags is None:
            tags = {}

        key = self._metric_key(name, tags)

        if key in self.gauges:
            return self.gauges[key]

        with self._lock:
            # Double-check after lock
            if key in self.gauges:
                return self.gauges[key]

            gauge = GaugeImpl(name, tags.copy(), self.buffer)
            self.gauges[key] = gauge
            return gauge

    def histogram(self, name: str, tags: Dict[str, str] = None) -> Histogram:
        """Get or create a histogram"""
        if tags is None:
            tags = {}

        key = self._metric_key(name, tags)

        if key in self.histograms:
            return self.histograms[key]

        with self._lock:
            # Double-check after lock
            if key in self.histograms:
                return self.histograms[key]

            histogram = HistogramImpl(name, tags.copy(), self.buffer)
            self.histograms[key] = histogram
            return histogram

    def shutdown(self) -> None:
        """Shutdown metrics registry"""
        self.buffer.shutdown()

    @staticmethod
    def _metric_key(name: str, tags: Dict[str, str]) -> str:
        """Create unique key for metric"""
        if not tags:
            return name

        # Simple key format: name{k1=v1,k2=v2}
        tag_pairs = sorted(f"{k}={v}" for k, v in tags.items())
        return f"{name}{{{','.join(tag_pairs)}}}"


# No-op implementations for when metrics are disabled
class NoopCounter(Counter):
    def inc(self) -> None:
        pass

    def add(self, value: float) -> None:
        pass


class NoopGauge(Gauge):
    def set(self, value: float) -> None:
        pass

    def inc(self) -> None:
        pass

    def dec(self) -> None:
        pass


class NoopHistogram(Histogram):
    def record(self, value: float) -> None:
        pass


noop_counter = NoopCounter()
noop_gauge = NoopGauge()
noop_histogram = NoopHistogram()
