"""
TraceKit Client - Main tracing client using OpenTelemetry
"""

import os
import random
import traceback
from dataclasses import dataclass
from typing import Any, Dict, Optional

from opentelemetry import trace, context
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanProcessor, SpanExportResult
from opentelemetry.trace import Span, Status, StatusCode
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.urllib import URLLibInstrumentor
from opentelemetry.instrumentation.urllib3 import URLLib3Instrumentor
from opentelemetry.sdk.trace import ReadableSpan

from tracekit.snapshot_client import SnapshotClient


def _detect_local_ui() -> bool:
    """
    Detect if TraceKit Local UI is running at http://localhost:9999.

    Returns:
        True if local UI is available, False otherwise
    """
    try:
        import requests
        response = requests.get('http://localhost:9999/api/health', timeout=0.5)
        return response.ok
    except:
        return False


def _is_development_mode() -> bool:
    """
    Check if running in development mode based on environment variables.

    Returns:
        True if in development mode, False otherwise
    """
    env = os.getenv('ENV', '').lower()
    node_env = os.getenv('NODE_ENV', '').lower()
    return env == 'development' or node_env == 'development'


class LocalUISpanProcessor(SpanProcessor):
    """
    Custom span processor that sends traces to TraceKit Local UI in development mode.
    This runs in addition to the main cloud exporter.
    """

    def __init__(self):
        self.local_ui_available = False
        self.local_ui_checked = False
        self.local_ui_url = 'http://localhost:9999/v1/traces'

    def on_start(self, span: ReadableSpan, parent_context=None) -> None:
        """Called when a span is started."""
        pass

    def on_end(self, span: ReadableSpan) -> None:
        """Called when a span is ended. Send to local UI if available."""
        # Only check once per process
        if not self.local_ui_checked:
            self.local_ui_checked = True
            self.local_ui_available = _detect_local_ui()
            if self.local_ui_available:
                print('🔍 Local UI detected at http://localhost:9999')

        if not self.local_ui_available:
            return

        # Send to local UI using the same OTLP format
        try:
            import requests
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            # Create a temporary exporter for local UI
            exporter = OTLPSpanExporter(
                endpoint=self.local_ui_url,
                timeout=1
            )

            # Export the span
            exporter.export([span])
        except Exception:
            # Silently fail - don't block trace sending to cloud
            pass

    def shutdown(self) -> None:
        """Called when the processor is shut down."""
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Force flush any pending spans."""
        return True


@dataclass
class TracekitConfig:
    """Configuration for TraceKit client"""
    api_key: str
    service_name: str = "python-app"
    endpoint: str = "https://app.tracekit.dev/v1/traces"
    enabled: bool = True
    sample_rate: float = 1.0
    enable_code_monitoring: bool = False
    auto_instrument_http_client: bool = True
    # Map hostnames to service names for peer.service attribute
    # Useful for mapping localhost URLs to actual service names
    # Example: {"localhost:8082": "go-test-app", "localhost:8084": "node-test-app"}
    service_name_mappings: Optional[Dict[str, str]] = None


class TracekitClient:
    """
    Main TraceKit client for distributed tracing and code monitoring.

    Uses OpenTelemetry for standards-based distributed tracing.
    """

    def __init__(self, config: TracekitConfig):
        self.config = config
        self._snapshot_client: Optional[SnapshotClient] = None

        # Create resource with service name
        resource = Resource(attributes={
            SERVICE_NAME: config.service_name
        })

        # Initialize tracer provider
        self.provider = TracerProvider(resource=resource)

        if config.enabled:
            # Configure OTLP exporter for cloud
            exporter = OTLPSpanExporter(
                endpoint=config.endpoint,
                headers={"X-API-Key": config.api_key}
            )

            # Use batch processor for better performance
            self.provider.add_span_processor(BatchSpanProcessor(exporter))

            # Add local UI processor in development mode
            if _is_development_mode():
                self.provider.add_span_processor(LocalUISpanProcessor())

            # Register the provider
            trace.set_tracer_provider(self.provider)

            # Auto-instrument HTTP clients for CLIENT span creation
            if config.auto_instrument_http_client:
                self._instrument_http_clients()

        self.tracer = trace.get_tracer(__name__, "1.0.0")

        # Initialize snapshot client if enabled
        if config.enable_code_monitoring:
            base_url = config.endpoint.replace("/v1/traces", "")
            self._snapshot_client = SnapshotClient(
                api_key=config.api_key,
                base_url=base_url,
                service_name=config.service_name
            )
            self._snapshot_client.start()

    def start_trace(
        self,
        operation_name: str,
        attributes: Optional[Dict[str, Any]] = None
    ) -> Span:
        """
        Start a new root trace span (server request).

        Args:
            operation_name: Name of the operation
            attributes: Optional attributes to add to the span

        Returns:
            OpenTelemetry Span object
        """
        span = self.tracer.start_span(
            operation_name,
            kind=trace.SpanKind.SERVER,
            attributes=self._normalize_attributes(attributes or {})
        )
        return span

    def start_server_span(
        self,
        operation_name: str,
        attributes: Optional[Dict[str, Any]] = None,
        parent_context: Optional[Any] = None
    ) -> Span:
        """
        Start a SERVER span, properly inheriting from the provided context.
        This is used by middleware to create spans that are children of incoming trace context.

        Args:
            operation_name: Name of the operation
            attributes: Optional attributes to add to the span
            parent_context: Optional parent context from traceparent header extraction

        Returns:
            OpenTelemetry Span object
        """
        ctx = parent_context if parent_context else context.get_current()
        span = self.tracer.start_span(
            operation_name,
            kind=trace.SpanKind.SERVER,
            attributes=self._normalize_attributes(attributes or {}),
            context=ctx
        )
        return span

    def start_span(
        self,
        operation_name: str,
        attributes: Optional[Dict[str, Any]] = None
    ) -> Span:
        """
        Start a new child span. Automatically inherits from the currently active span.

        Args:
            operation_name: Name of the operation
            attributes: Optional attributes to add to the span

        Returns:
            OpenTelemetry Span object
        """
        span = self.tracer.start_span(
            operation_name,
            kind=trace.SpanKind.INTERNAL,
            attributes=self._normalize_attributes(attributes or {})
        )
        return span

    def end_span(
        self,
        span: Span,
        final_attributes: Optional[Dict[str, Any]] = None,
        status: str = "OK"
    ) -> None:
        """
        End a span with optional final attributes.

        Args:
            span: The span to end
            final_attributes: Optional attributes to add before ending
            status: Span status ('OK' or 'ERROR')
        """
        if final_attributes:
            span.set_attributes(self._normalize_attributes(final_attributes))

        if status == "ERROR":
            span.set_status(Status(StatusCode.ERROR))
        elif status == "OK":
            span.set_status(Status(StatusCode.OK))

        span.end()

    def add_event(
        self,
        span: Span,
        name: str,
        attributes: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Add an event to a span.

        Args:
            span: The span to add the event to
            name: Name of the event
            attributes: Optional attributes for the event
        """
        span.add_event(name, attributes=self._normalize_attributes(attributes or {}))

    def record_exception(
        self,
        span: Span,
        exception: Exception
    ) -> None:
        """
        Record an exception on a span with formatted stack trace for code discovery.

        Args:
            span: The span to record the exception on
            exception: The exception to record
        """
        # Format stack trace for code discovery
        formatted_stacktrace = self._format_stacktrace(exception)

        # Record exception as an event with formatted stack trace
        span.add_event(
            "exception",
            attributes={
                "exception.type": type(exception).__name__,
                "exception.message": str(exception),
                "exception.stacktrace": formatted_stacktrace,
            }
        )

        # Also use standard OpenTelemetry exception recording
        span.record_exception(exception)

        span.set_status(Status(StatusCode.ERROR, str(exception)))

    def _format_stacktrace(self, exception: Exception) -> str:
        """
        Format stack trace for code discovery.
        Returns native Python traceback format which matches backend expectations:
        File "filename.py", line 123, in function_name

        Args:
            exception: The exception to format

        Returns:
            Native Python stack trace string
        """
        tb_lines = traceback.format_exception(
            type(exception),
            exception,
            exception.__traceback__
        )

        # Return native Python traceback format - backend expects this exact format
        # Pattern: File "([^"]+)", line (\d+), in (\S+)
        return "".join(tb_lines)

    async def flush(self) -> None:
        """Force flush all pending spans to the backend."""
        if self.config.enabled:
            self.provider.force_flush()

    async def shutdown(self) -> None:
        """Shutdown the tracer provider and snapshot client."""
        # Stop snapshot client first
        if self._snapshot_client:
            self._snapshot_client.stop()

        # Shutdown tracing provider
        if self.config.enabled:
            self.provider.shutdown()

    def is_enabled(self) -> bool:
        """Check if tracing is enabled."""
        return self.config.enabled and bool(self.config.api_key)

    def should_sample(self) -> bool:
        """Determine if the current request should be sampled."""
        return random.random() < self.config.sample_rate

    def get_tracer(self) -> trace.Tracer:
        """Get the underlying OpenTelemetry tracer."""
        return self.tracer

    def get_snapshot_client(self) -> Optional[SnapshotClient]:
        """Get the snapshot client if code monitoring is enabled."""
        return self._snapshot_client

    def capture_snapshot(
        self,
        label: str,
        variables: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Convenience method for capturing snapshots.

        Args:
            label: Label for the snapshot
            variables: Variables to capture
        """
        if self._snapshot_client:
            self._snapshot_client.check_and_capture_with_context(
                label,
                variables or {}
            )

    def _instrument_http_clients(self) -> None:
        """
        Auto-instrument HTTP client libraries to create CLIENT spans
        with peer.service attribute for service dependency mapping.
        """
        # Instrument requests library (most common)
        try:
            RequestsInstrumentor().instrument(
                tracer_provider=self.provider,
                request_hook=self._http_request_hook,
            )
        except Exception as e:
            # Ignore if already instrumented or not available
            pass

        # Instrument urllib
        try:
            URLLibInstrumentor().instrument(
                tracer_provider=self.provider,
                request_hook=self._http_request_hook,
            )
        except Exception as e:
            pass

        # Instrument urllib3
        try:
            URLLib3Instrumentor().instrument(
                tracer_provider=self.provider,
                request_hook=self._http_request_hook,
            )
        except Exception as e:
            pass

    def _http_request_hook(self, span: Span, request: Any) -> None:
        """
        Hook called for outgoing HTTP requests to add peer.service attribute.

        Args:
            span: The CLIENT span being created
            request: The request object (varies by library)
        """
        try:
            # Extract hostname from request (different per library)
            hostname = None

            # requests library
            if hasattr(request, 'url'):
                from urllib.parse import urlparse
                parsed = urlparse(request.url)
                hostname = parsed.hostname
            # urllib/urllib3
            elif hasattr(request, 'host'):
                hostname = request.host

            if hostname:
                service_name = self._extract_service_name(hostname)
                span.set_attribute("peer.service", service_name)
        except Exception:
            # Don't fail request if attribute extraction fails
            pass

    def _extract_service_name(self, hostname: str) -> str:
        """
        Extract service name from hostname for service-to-service mapping.

        Examples:
            "payment-service" -> "payment-service"
            "payment.internal.svc.cluster.local" -> "payment"
            "api.example.com" -> "api.example.com"

        Args:
            hostname: The hostname to extract from

        Returns:
            Extracted service name
        """
        if not hostname:
            return "unknown"

        # First, check if there's a configured mapping for this hostname
        # This allows mapping localhost:port to actual service names
        if self.config.service_name_mappings:
            if hostname in self.config.service_name_mappings:
                return self.config.service_name_mappings[hostname]

            # Also check without port
            host_without_port = hostname.split(":")[0]
            if host_without_port in self.config.service_name_mappings:
                return self.config.service_name_mappings[host_without_port]

        # Handle Kubernetes service names
        if ".svc.cluster.local" in hostname:
            return hostname.split(".")[0]

        # Handle internal domain
        if ".internal" in hostname:
            return hostname.split(".")[0]

        # Default: return full hostname (strip port if present)
        return hostname.split(":")[0]

    def _normalize_attributes(self, attributes: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize attributes to OpenTelemetry compatible types.

        Args:
            attributes: Raw attributes dictionary

        Returns:
            Normalized attributes dictionary
        """
        normalized = {}
        for key, value in attributes.items():
            if isinstance(value, (str, int, float, bool)):
                normalized[key] = value
            elif isinstance(value, (list, tuple)):
                normalized[key] = [str(v) for v in value]
            else:
                normalized[key] = str(value)
        return normalized
