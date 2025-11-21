"""
TraceKit APM for Python

Zero-config distributed tracing and code monitoring for Flask, FastAPI, and Django applications.
"""

from typing import Dict, Optional
from tracekit.client import TracekitClient, TracekitConfig
from tracekit.snapshot_client import SnapshotClient

__version__ = "1.0.0"
__all__ = [
    "TracekitClient",
    "TracekitConfig",
    "SnapshotClient",
    "init",
    "get_client",
]

# Global client instance
_global_client: Optional[TracekitClient] = None


def init(
    api_key: str,
    service_name: str = "python-app",
    endpoint: str = "https://app.tracekit.dev/v1/traces",
    enabled: bool = True,
    sample_rate: float = 1.0,
    enable_code_monitoring: bool = False,
    service_name_mappings: Optional[Dict[str, str]] = None,
) -> TracekitClient:
    """
    Initialize TraceKit APM with the given configuration.

    Args:
        api_key: Your TraceKit API key
        service_name: Name of your service (default: 'python-app')
        endpoint: TraceKit endpoint URL (default: 'https://app.tracekit.dev/v1/traces')
        enabled: Enable/disable tracing (default: True)
        sample_rate: Sample rate 0.0-1.0 (default: 1.0 = 100%)
        enable_code_monitoring: Enable live code debugging (default: False)
        service_name_mappings: Map hostnames to service names for peer.service attribute
            Example: {"localhost:8082": "go-test-app", "localhost:8084": "node-test-app"}

    Returns:
        TracekitClient instance
    """
    global _global_client

    config = TracekitConfig(
        api_key=api_key,
        service_name=service_name,
        endpoint=endpoint,
        enabled=enabled,
        sample_rate=sample_rate,
        enable_code_monitoring=enable_code_monitoring,
        service_name_mappings=service_name_mappings,
    )

    _global_client = TracekitClient(config)
    return _global_client


def get_client() -> TracekitClient:
    """
    Get the global TracekitClient instance.

    Returns:
        TracekitClient instance

    Raises:
        RuntimeError: If TraceKit has not been initialized
    """
    if _global_client is None:
        raise RuntimeError(
            "TraceKit not initialized. Call tracekit.init() first."
        )
    return _global_client
