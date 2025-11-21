# TraceKit APM for Python

Zero-config distributed tracing and performance monitoring for Flask, FastAPI, and Django applications.

[![PyPI version](https://img.shields.io/pypi/v/tracekit-apm.svg)](https://pypi.org/project/tracekit-apm/)
[![Python](https://img.shields.io/pypi/pyversions/tracekit-apm.svg)](https://pypi.org/project/tracekit-apm/)
[![License](https://img.shields.io/pypi/l/tracekit-apm.svg)](https://pypi.org/project/tracekit-apm/)

## Features

- ✅ **Zero Configuration** - Works out of the box with sensible defaults
- ✅ **Automatic Instrumentation** - No code changes needed
- ✅ **Flask Support** - Simple middleware integration
- ✅ **FastAPI Support** - ASGI middleware-based tracing
- ✅ **Django Support** - Django middleware integration
- ✅ **HTTP Request Tracing** - Track every request, route, and handler
- ✅ **Error Tracking** - Capture exceptions with full Python stack traces
- ✅ **Code Discovery** - Automatically index code from exception stack traces
- ✅ **Code Monitoring** - Live debugging with breakpoints and variable inspection
- ✅ **Nested Spans** - Parent-child span relationships with OpenTelemetry
- ✅ **Low Overhead** - < 5% performance impact
- ✅ **OpenTelemetry Standard** - Built on industry-standard OpenTelemetry

## Installation

```bash
pip install tracekit-apm
```

### Framework-Specific Installation

```bash
# Flask
pip install tracekit-apm[flask]

# FastAPI
pip install tracekit-apm[fastapi]

# Django
pip install tracekit-apm[django]

# All frameworks
pip install tracekit-apm[all]
```

## Quick Start

### Flask

```python
from flask import Flask
import tracekit
from tracekit.middleware.flask import init_flask_app

app = Flask(__name__)

# Initialize TraceKit with code monitoring enabled
client = tracekit.init(
    api_key="your-api-key",
    service_name="my-flask-app",
    enable_code_monitoring=True  # Enable live debugging
)

# Add middleware
init_flask_app(app, client)

@app.route('/')
def hello():
    return 'Hello World!'

@app.route('/api/users/<int:user_id>')
def get_user(user_id):
    # Capture snapshot for debugging (synchronous call)
    if client.get_snapshot_client():
        client.capture_snapshot('get-user', {
            'user_id': user_id,
            'request_path': request.path,
            'request_method': request.method
        })

    # Your business logic here
    user = fetch_user_from_db(user_id)
    return jsonify(user)

if __name__ == '__main__':
    app.run()
```

### FastAPI

```python
from fastapi import FastAPI
import tracekit
from tracekit.middleware.fastapi import init_fastapi_app

app = FastAPI()

# Initialize TraceKit
client = tracekit.init(
    api_key="your-api-key",
    service_name="my-fastapi-app"
)

# Add middleware
init_fastapi_app(app, client)

@app.get("/")
async def root():
    return {"message": "Hello World"}
```

### Django

```python
# settings.py

# Add middleware
MIDDLEWARE = [
    'tracekit.middleware.django.TracekitDjangoMiddleware',
    # ... other middleware
]

# Initialize TraceKit in your app's apps.py
# apps.py
from django.apps import AppConfig
import tracekit
import os

class MyAppConfig(AppConfig):
    name = 'myapp'

    def ready(self):
        tracekit.init(
            api_key=os.environ['TRACEKIT_API_KEY'],
            service_name='my-django-app'
        )
```

## Code Monitoring (Live Debugging)

TraceKit includes production-safe code monitoring for live debugging without redeployment.

### Enable Code Monitoring

```python
import tracekit

# Enable code monitoring
client = tracekit.init(
    api_key="your-api-key",
    service_name="my-app",
    enable_code_monitoring=True  # Enable live debugging
)
```

### Add Debug Points

Add checkpoints anywhere in your code to capture variable state and stack traces:

```python
@app.post('/checkout')
async def checkout(request):
    cart = await request.json()
    user_id = cart['user_id']

    # Capture snapshot at this point (synchronous - no await needed)
    client.capture_snapshot('checkout-validation', {
        'user_id': user_id,
        'cart_items': len(cart.get('items', [])),
        'total_amount': cart.get('total', 0),
    })

    # Process payment...
    result = await process_payment(cart)

    # Another checkpoint
    client.capture_snapshot('payment-complete', {
        'user_id': user_id,
        'payment_id': result['payment_id'],
        'success': result['success'],
    })

    return {'status': 'success', 'result': result}
```

### Automatic Breakpoint Management

- **Auto-Registration**: First call to `capture_snapshot()` automatically creates breakpoints in TraceKit
- **Smart Matching**: Breakpoints match by function name + label (stable across code changes)
- **Background Sync**: SDK polls for active breakpoints every 30 seconds
- **Production Safe**: No performance impact when breakpoints are inactive
- **Synchronous API**: `capture_snapshot()` is synchronous - no `await` needed (works in both sync and async code)

### Important Notes

🔑 **Key Points:**
- `capture_snapshot()` is **synchronous** (no `await` needed)
- Works in both sync and async functions
- Automatically registers breakpoints on first call
- Captures are rate-limited (1 per second per breakpoint)
- Max 100 captures per breakpoint by default

### View Captured Data

Snapshots include:
- **Variables**: Local variables at capture point
- **Stack Trace**: Full call stack with file/line numbers
- **Request Context**: HTTP method, URL, headers, query params
- **Execution Time**: When the snapshot was captured

Get your API key at [https://app.tracekit.dev](https://app.tracekit.dev)

## Configuration

### Basic Configuration

```python
import tracekit

client = tracekit.init(
    # Required: Your TraceKit API key
    api_key="your-api-key",

    # Optional: Service name (default: 'python-app')
    service_name="my-service",

    # Optional: TraceKit endpoint (default: 'https://app.tracekit.dev/v1/traces')
    endpoint="https://app.tracekit.dev/v1/traces",

    # Optional: Enable/disable tracing (default: True)
    enabled=True,

    # Optional: Sample rate 0.0-1.0 (default: 1.0 = 100%)
    sample_rate=0.5,  # Trace 50% of requests

    # Optional: Enable live code debugging (default: False)
    enable_code_monitoring=True
)
```

### Environment Variables

Create a `.env` file or set these environment variables:

```bash
TRACEKIT_API_KEY=your_api_key_here
TRACEKIT_ENDPOINT=https://app.tracekit.dev/v1/traces
TRACEKIT_SERVICE_NAME=my-python-app
```

Then use them in your code:

```python
import os
import tracekit

client = tracekit.init(
    api_key=os.getenv('TRACEKIT_API_KEY'),
    service_name=os.getenv('TRACEKIT_SERVICE_NAME', 'python-app'),
    endpoint=os.getenv('TRACEKIT_ENDPOINT', 'https://app.tracekit.dev/v1/traces')
)
```

## What Gets Traced?

### HTTP Requests

Every HTTP request is automatically traced with:

- Route path and HTTP method
- Request URL and query parameters
- HTTP status code
- Request duration
- User agent and client IP
- Controller and handler names

### Errors and Exceptions

All exceptions are automatically captured with:

- Exception type and message
- Full stack trace (Python format preserved)
- Request context
- Handler information

### Automatic Code Discovery

TraceKit automatically discovers and indexes your Python code from exception stack traces:

**Python Stack Trace Format (Native):**
```python
File "/path/to/app.py", line 123, in function_name
```

**What Gets Indexed:**
- File paths: `app.py`, `handlers.py`, etc.
- Function names: `get_user`, `process_payment`, etc.
- Line numbers: Exact location in your code
- First/last seen timestamps
- Occurrence counts

**Example:**
When this exception occurs:
```python
File "/app/handlers/users.py", line 42, in get_user
    user = User.objects.get(id=user_id)
DoesNotExist: User matching query does not exist.
```

TraceKit indexes:
- **File**: `users.py`
- **Function**: `get_user`
- **Line**: 42
- **Service**: Your service name

View discovered code in the TraceKit UI under **Code Inventory**.

## Advanced Usage

### Manual Tracing

```python
from opentelemetry import trace

@app.post('/process-order')
async def process_order(request):
    # Get the client
    client = tracekit.get_client()

    # Start a custom span
    span = client.start_span('process-order', {
        'order.id': order_id,
        'customer.id': customer_id
    })

    try:
        # Your business logic
        result = await process_order_logic(order_id)

        # Add attributes
        client.end_span(span, {
            'order.status': result['status'],
            'order.total': result['total']
        })

        return result

    except Exception as error:
        # Record exception
        client.record_exception(span, error)
        client.end_span(span, {}, status='ERROR')
        raise
```

### Custom Spans with Context Manager (Nested Spans)

Use OpenTelemetry's context manager for automatic parent-child span relationships:

```python
from opentelemetry import trace
from flask import Flask, jsonify
import time

@app.route('/api/users/<int:user_id>')
def get_user(user_id):
    # Get the tracer
    tracer = trace.get_tracer(__name__)

    # Parent span is automatically managed by Flask middleware
    # Create child span using context manager
    with tracer.start_as_current_span('db.query.user') as span:
        span.set_attributes({
            'db.system': 'postgresql',
            'db.operation': 'SELECT',
            'db.table': 'users',
            'db.statement': 'SELECT * FROM users WHERE id = ?',
            'user.id': user_id
        })

        time.sleep(0.01)  # Simulate DB query
        user = fetch_user_from_db(user_id)

        span.set_attributes({
            'user.found': user is not None,
            'user.role': user.get('role') if user else None
        })

    return jsonify(user)
```

This creates a **nested trace** with parent-child relationships:
```
GET /api/users/1 (parent span - auto-created by middleware)
  └─ db.query.user (child span - manually created)
```

### Database Query Tracing

```python
@app.get('/users')
async def list_users():
    client = tracekit.get_client()

    # Start a database query span
    span = client.start_span('db.query.users', {
        'db.system': 'postgresql',
        'db.operation': 'SELECT',
        'db.table': 'users'
    })

    try:
        users = await db.query('SELECT * FROM users')

        client.end_span(span, {
            'db.rows_affected': len(users)
        })

        return users

    except Exception as error:
        client.record_exception(span, error)
        client.end_span(span, {}, status='ERROR')
        raise
```

### External API Call Tracing

```python
import httpx

@app.get('/external-data')
async def fetch_external_data():
    client = tracekit.get_client()

    span = client.start_span('http.client.get', {
        'http.url': 'https://api.example.com/data',
        'http.method': 'GET'
    })

    try:
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get('https://api.example.com/data')

        client.end_span(span, {
            'http.status_code': response.status_code,
            'response.size': len(response.content)
        })

        return response.json()

    except Exception as error:
        client.record_exception(span, error)
        client.end_span(span, {}, status='ERROR')
        raise
```

## Environment-Based Configuration

### Disable tracing in development

```python
import os

tracekit.init(
    api_key=os.getenv('TRACEKIT_API_KEY'),
    enabled=os.getenv('ENVIRONMENT') == 'production'
)
```

### Sample only 10% of requests

```python
tracekit.init(
    api_key=os.getenv('TRACEKIT_API_KEY'),
    sample_rate=0.1  # Trace 10% of requests
)
```

## Performance

TraceKit APM is designed to have minimal performance impact:

- **< 5% overhead** on average request time
- Asynchronous trace sending (doesn't block responses)
- Automatic batching and compression
- Configurable sampling for high-traffic apps

## Requirements

- Python 3.8 or higher
- Flask 2.0+ (for Flask support)
- FastAPI 0.100+ (for FastAPI support)
- Django 3.2+ (for Django support)

## Examples

See the [examples/](examples/) directory for complete working applications:

- Flask example: [examples/flask_example.py](examples/flask_example.py)
- FastAPI example: [examples/fastapi_example.py](examples/fastapi_example.py)
- Django example: [examples/django_example/](examples/django_example/)

## Troubleshooting

### Snapshots Not Capturing

If snapshots are registered but not capturing:

1. **Check if code monitoring is enabled:**
   ```python
   client = tracekit.init(
       api_key="your-api-key",
       enable_code_monitoring=True  # Must be True
   )
   ```

2. **Verify snapshot client is available:**
   ```python
   if client.get_snapshot_client():
       client.capture_snapshot('label', {'var': value})
   ```

3. **Check backend logs for errors:**
   - Look for "Snapshot captured successfully" messages
   - Check for datetime format errors (should use UTC with Z suffix)

### Code Discovery Not Working

If Python code isn't being indexed:

1. **Trigger an exception** - Code discovery works from exception stack traces
2. **Check stack trace format** - Should be native Python format:
   ```
   File "/path/to/file.py", line 123, in function_name
   ```
3. **View backend logs** - Look for "Parsed X frames from stack trace"

### Context Token Errors

If you see `RuntimeError: Token has already been used once`:

- This was fixed in the latest version
- Make sure you're using the latest `tracekit-apm` package
- The error occurs when exceptions are not properly cleaned up

### Nested Spans Not Showing

To create nested spans, use OpenTelemetry's context manager:

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

# This creates a child span under the parent request span
with tracer.start_as_current_span('operation-name') as span:
    span.set_attribute('key', 'value')
    # Your code here
```

## Support

- Documentation: [https://app.tracekit.dev/docs/languages/python](https://app.tracekit.dev/docs/languages/python)
- Issues: [https://github.com/Tracekit-Dev/python-apm/issues](https://github.com/Tracekit-Dev/python-apm/issues)
- Email: support@tracekit.dev

## License

MIT License. See [LICENSE](LICENSE) for details.

## Credits

Built with ❤️ by the TraceKit team using OpenTelemetry.
