"""
TraceKit Client - Main tracing client using OpenTelemetry
"""

import random
import traceback
from dataclasses import dataclass
from typing import Any, Dict, Optional

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, Status, StatusCode

from tracekit.snapshot_client import SnapshotClient


@dataclass
class TracekitConfig:
    """Configuration for TraceKit client"""
    api_key: str
    service_name: str = "python-app"
    endpoint: str = "https://app.tracekit.dev/v1/traces"
    enabled: bool = True
    sample_rate: float = 1.0
    enable_code_monitoring: bool = False


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
            # Configure OTLP exporter
            exporter = OTLPSpanExporter(
                endpoint=config.endpoint,
                headers={"X-API-Key": config.api_key}
            )

            # Use batch processor for better performance
            self.provider.add_span_processor(BatchSpanProcessor(exporter))

            # Register the provider
            trace.set_tracer_provider(self.provider)

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
