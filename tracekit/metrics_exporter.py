"""
TraceKit Metrics Exporter - Exports metrics to backend in OTLP format
"""

from typing import List, Dict, Any
from urllib.parse import urlparse
import http.client
import json


class MetricsExporter:
    """MetricsExporter sends metrics to the backend in OTLP format"""

    def __init__(self, endpoint: str, api_key: str, service_name: str):
        self.endpoint = endpoint
        self.api_key = api_key
        self.service_name = service_name

    def export(self, data_points: List[Any]) -> None:
        """Export metrics to backend"""
        if not data_points:
            return

        payload = self._to_otlp(data_points)
        body = json.dumps(payload).encode('utf-8')

        # Parse endpoint URL
        url = urlparse(self.endpoint)
        is_https = url.scheme == 'https'

        # Create connection
        if is_https:
            conn = http.client.HTTPSConnection(url.hostname, url.port or 443, timeout=10)
        else:
            conn = http.client.HTTPConnection(url.hostname, url.port or 80, timeout=10)

        try:
            # Send request
            headers = {
                'Content-Type': 'application/json',
                'Content-Length': str(len(body)),
                'X-API-Key': self.api_key
            }

            conn.request('POST', url.path, body=body, headers=headers)
            response = conn.getresponse()

            if response.status != 200:
                raise Exception(f"HTTP {response.status}")

            # Consume response
            response.read()
        finally:
            conn.close()

    def _to_otlp(self, data_points: List[Any]) -> Dict[str, Any]:
        """Convert metrics to OTLP format"""
        # Group by name and type
        grouped: Dict[str, List[Any]] = {}

        for dp in data_points:
            key = f"{dp.name}:{dp.metric_type}"
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(dp)

        # Build metrics array
        metrics = []

        for key, dps in grouped.items():
            name, metric_type = key.split(':', 1)

            # Convert data points
            otlp_data_points = []
            for dp in dps:
                attributes = [
                    {
                        'key': k,
                        'value': {'stringValue': v}
                    }
                    for k, v in dp.tags.items()
                ]

                otlp_data_points.append({
                    'attributes': attributes,
                    'timeUnixNano': str(int(dp.timestamp * 1_000_000_000)),  # Convert to nanoseconds
                    'asDouble': dp.value
                })

            # Create metric based on type
            if metric_type == 'counter':
                metric = {
                    'name': name,
                    'sum': {
                        'dataPoints': otlp_data_points,
                        'aggregationTemporality': 2,  # DELTA
                        'isMonotonic': True
                    }
                }
            else:  # gauge or histogram
                metric = {
                    'name': name,
                    'gauge': {
                        'dataPoints': otlp_data_points
                    }
                }

            metrics.append(metric)

        return {
            'resourceMetrics': [
                {
                    'resource': {
                        'attributes': [
                            {
                                'key': 'service.name',
                                'value': {'stringValue': self.service_name}
                            }
                        ]
                    },
                    'scopeMetrics': [
                        {
                            'scope': {
                                'name': 'tracekit'
                            },
                            'metrics': metrics
                        }
                    ]
                }
            ]
        }
