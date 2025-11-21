"""
Django middleware for TraceKit APM
"""

import time
from typing import Callable, Optional

from opentelemetry import trace, context
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from tracekit.client import TracekitClient

# W3C Trace Context propagator for extracting traceparent header
_propagator = TraceContextTextMapPropagator()


class TracekitDjangoMiddleware:
    """
    Django middleware for automatic request tracing.

    Usage in Django settings.py:
        MIDDLEWARE = [
            'tracekit.middleware.django.TracekitDjangoMiddleware',
            # ... other middleware
        ]

        # Initialize TraceKit in your app's __init__.py or ready() method
        import tracekit
        tracekit.init(
            api_key=os.environ['TRACEKIT_API_KEY'],
            service_name='my-django-app'
        )
    """

    def __init__(self, get_response: Callable):
        self.get_response = get_response

        # Try to get the global client
        try:
            import tracekit
            self.client = tracekit.get_client()
        except RuntimeError:
            raise RuntimeError(
                "TraceKit not initialized. Call tracekit.init() before starting Django."
            )

    def __call__(self, request):
        """
        Process each request and add tracing.

        Args:
            request: Django HttpRequest object

        Returns:
            Django HttpResponse object
        """
        if not self.client.is_enabled() or not self.client.should_sample():
            return self.get_response(request)

        # Get route pattern if available
        route_path = request.path
        if hasattr(request, "resolver_match") and request.resolver_match:
            route_path = request.resolver_match.route or request.path

        # Extract trace context from incoming request headers (W3C Trace Context)
        # Django headers are in META with HTTP_ prefix, convert to standard format
        headers = {}
        for key, value in request.META.items():
            if key.startswith("HTTP_"):
                # Convert HTTP_TRACEPARENT to traceparent
                header_name = key[5:].lower().replace("_", "-")
                headers[header_name] = value
        parent_context = _propagator.extract(carrier=headers)

        # Start trace span with parent context (if any)
        span = self.client.start_server_span(
            f"{request.method} {route_path}",
            attributes={
                "http.method": request.method,
                "http.url": request.build_absolute_uri(),
                "http.route": route_path,
                "http.user_agent": request.META.get("HTTP_USER_AGENT"),
                "http.client_ip": self._get_client_ip(request),
            },
            parent_context=parent_context
        )

        # Activate span in context
        token = trace.use_span(span, end_on_exit=False)
        start_time = time.time()

        try:
            # Process request
            response = self.get_response(request)

            # Calculate duration
            duration_ms = (time.time() - start_time) * 1000

            # Add response attributes
            self.client.end_span(
                span,
                final_attributes={
                    "http.status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
                status="OK" if response.status_code < 400 else "ERROR"
            )

            return response

        except Exception as error:
            # Record exception
            self.client.record_exception(span, error)
            self.client.end_span(span, {}, status="ERROR")
            raise

        finally:
            # Detach context
            context.detach(token)

    def _get_client_ip(self, request) -> Optional[str]:
        """Extract client IP from request."""
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")
