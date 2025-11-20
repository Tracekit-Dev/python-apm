"""
Middleware integrations for Flask, FastAPI, and Django
"""

from tracekit.middleware.flask import create_flask_middleware

__all__ = [
    "create_flask_middleware",
]

# Optional imports - only import if dependencies are available
try:
    from tracekit.middleware.fastapi import create_fastapi_middleware
    __all__.append("create_fastapi_middleware")
except ImportError:
    pass
