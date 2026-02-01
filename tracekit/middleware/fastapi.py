"""
FastAPI middleware for TraceKit APM
"""

import time
from typing import Callable

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from opentelemetry import trace, context
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from tracekit.client import TracekitClient
from tracekit.utils import extract_client_ip_from_headers

# W3C Trace Context propagator for extracting traceparent header
_propagator = TraceContextTextMapPropagator()


class TracekitMiddleware(BaseHTTPMiddleware):
    """
    FastAPI/Starlette middleware for automatic request tracing.
    """

    def __init__(self, app: ASGIApp, client: TracekitClient):
        super().__init__(app)
        self.client = client

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process each request and add tracing.

        Args:
            request: Incoming request
            call_next: Next middleware/handler in chain

        Returns:
            Response object
        """
        if not self.client.is_enabled() or not self.client.should_sample():
            return await call_next(request)

        # Extract route path (if available)
        route_path = request.url.path
        if hasattr(request, "scope") and "route" in request.scope:
            route = request.scope.get("route")
            if hasattr(route, "path"):
                route_path = route.path

        # Extract trace context from incoming request headers (W3C Trace Context)
        # This enables distributed tracing - the span will be linked to the parent trace
        parent_context = _propagator.extract(carrier=dict(request.headers))

        # Start trace span with parent context (if any)
        span = self.client.start_server_span(
            f"{request.method} {route_path}",
            attributes={
                "http.method": request.method,
                "http.url": str(request.url),
                "http.route": route_path,
                "http.user_agent": request.headers.get("user-agent"),
                "http.client_ip": extract_client_ip_from_headers(
                    dict(request.headers),
                    request.client.host if request.client else None
                ),
            },
            parent_context=parent_context
        )

        # Activate span in context
        token = trace.use_span(span, end_on_exit=False)
        start_time = time.time()

        try:
            # Process request
            response = await call_next(request)

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


def create_fastapi_middleware(client: TracekitClient) -> Callable:
    """
    Create FastAPI middleware factory.

    Usage:
        from fastapi import FastAPI
        from tracekit import init
        from tracekit.middleware.fastapi import create_fastapi_middleware

        app = FastAPI()
        tracekit_client = init(api_key="your-api-key", service_name="my-fastapi-app")

        middleware = create_fastapi_middleware(tracekit_client)
        app.add_middleware(middleware)

    Args:
        client: TracekitClient instance

    Returns:
        Middleware class
    """
    def middleware_factory(app: ASGIApp) -> TracekitMiddleware:
        return TracekitMiddleware(app, client)

    return middleware_factory


def init_fastapi_app(app: FastAPI, client: TracekitClient) -> None:
    """
    Initialize FastAPI app with TraceKit middleware.

    Usage:
        from fastapi import FastAPI
        from tracekit import init
        from tracekit.middleware.fastapi import init_fastapi_app

        app = FastAPI()
        tracekit_client = init(api_key="your-api-key", service_name="my-fastapi-app")
        init_fastapi_app(app, tracekit_client)

    Args:
        app: FastAPI application instance
        client: TracekitClient instance
    """
    app.add_middleware(TracekitMiddleware, client=client)
