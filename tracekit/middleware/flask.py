"""
Flask middleware for TraceKit APM
"""

import time
from typing import Callable, Optional

from flask import Flask, request, g
from opentelemetry import trace, context
from opentelemetry.trace import Span
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from tracekit.client import TracekitClient
from tracekit.snapshot_client import SnapshotClient

# W3C Trace Context propagator for extracting traceparent header
_propagator = TraceContextTextMapPropagator()


def create_flask_middleware(
    client: TracekitClient,
    snapshot_client: Optional[SnapshotClient] = None
) -> Callable:
    """
    Create Flask middleware for automatic request tracing.

    Usage:
        app = Flask(__name__)
        tracekit_middleware = create_flask_middleware(tracekit_client)
        app.before_request(tracekit_middleware.before_request)
        app.after_request(tracekit_middleware.after_request)
        app.errorhandler(Exception)(tracekit_middleware.handle_exception)

    Args:
        client: TracekitClient instance
        snapshot_client: Optional SnapshotClient for code monitoring

    Returns:
        Middleware instance with before_request, after_request, and handle_exception methods
    """

    class FlaskMiddleware:
        def __init__(self):
            self.client = client
            self.snapshot_client = snapshot_client

        def before_request(self):
            """Hook called before each request."""
            if not self.client.is_enabled() or not self.client.should_sample():
                return

            # Extract trace context from incoming request headers (W3C Trace Context)
            # This enables distributed tracing - the span will be linked to the parent trace
            parent_context = _propagator.extract(carrier=dict(request.headers))

            # Start trace span with parent context (if any)
            span = self.client.start_server_span(
                f"{request.method} {request.path}",
                attributes={
                    "http.method": request.method,
                    "http.url": request.url,
                    "http.route": request.endpoint or request.path,
                    "http.user_agent": request.user_agent.string if request.user_agent else None,
                    "http.client_ip": request.remote_addr,
                },
                parent_context=parent_context
            )

            # Store span in Flask's g object and activate context
            g.tracekit_span = span
            ctx = trace.set_span_in_context(span)
            g.tracekit_token = context.attach(ctx)
            g.tracekit_start_time = time.time()

        def after_request(self, response):
            """Hook called after each request."""
            span = getattr(g, "tracekit_span", None)
            token = getattr(g, "tracekit_token", None)
            start_time = getattr(g, "tracekit_start_time", None)

            if span:
                # Calculate duration
                duration_ms = (time.time() - start_time) * 1000 if start_time else 0

                # Add response attributes
                self.client.end_span(
                    span,
                    final_attributes={
                        "http.status_code": response.status_code,
                        "http.response_size": len(response.get_data()),
                        "duration_ms": duration_ms,
                    },
                    status="OK" if response.status_code < 400 else "ERROR"
                )

                # Detach context
                if token:
                    context.detach(token)

            return response

        def handle_exception(self, error):
            """Hook called when an exception occurs."""
            span = getattr(g, "tracekit_span", None)
            token = getattr(g, "tracekit_token", None)

            if span:
                # Record exception
                self.client.record_exception(span, error)
                self.client.end_span(span, {}, status="ERROR")

                # Detach context
                if token:
                    try:
                        context.detach(token)
                    except RuntimeError:
                        # Token already detached, ignore
                        pass

                # Clear from g so after_request doesn't try to handle it again
                g.tracekit_span = None
                g.tracekit_token = None

            # Re-raise the exception
            raise error

    return FlaskMiddleware()


def init_flask_app(app: Flask, client: TracekitClient) -> None:
    """
    Initialize Flask app with TraceKit middleware.

    Usage:
        from tracekit import init
        from tracekit.middleware.flask import init_flask_app

        tracekit_client = init(api_key="your-api-key", service_name="my-flask-app")
        init_flask_app(app, tracekit_client)

    Args:
        app: Flask application instance
        client: TracekitClient instance
    """
    middleware = create_flask_middleware(client, client.get_snapshot_client())

    app.before_request(middleware.before_request)
    app.after_request(middleware.after_request)

    @app.errorhandler(Exception)
    def handle_exception(error):
        return middleware.handle_exception(error)
