# Django Example with TraceKit APM

This guide shows how to integrate TraceKit APM with a Django application.

## Installation

```bash
pip install tracekit-apm[django]
```

## Configuration

### 1. Initialize TraceKit in your app's `apps.py`

```python
# myapp/apps.py

from django.apps import AppConfig
import tracekit
import os


class MyAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'myapp'

    def ready(self):
        # Initialize TraceKit
        tracekit.init(
            api_key=os.environ.get('TRACEKIT_API_KEY', 'demo-key'),
            service_name='django-example',
            enable_code_monitoring=True
        )
```

### 2. Add TraceKit middleware to `settings.py`

```python
# settings.py

MIDDLEWARE = [
    'tracekit.middleware.django.TracekitDjangoMiddleware',  # Add this at the top
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# TraceKit Configuration (optional - uses environment variables by default)
TRACEKIT_API_KEY = os.environ.get('TRACEKIT_API_KEY')
TRACEKIT_SERVICE_NAME = 'django-example'
TRACEKIT_ENABLED = os.environ.get('ENVIRONMENT') == 'production'
```

### 3. Use TraceKit in your views

```python
# myapp/views.py

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
import tracekit
import time


def index(request):
    """Simple homepage"""
    return JsonResponse({
        'message': 'Welcome to TraceKit Django Example',
        'endpoints': [
            '/',
            '/api/users/',
            '/api/users/<id>/',
            '/api/slow/',
            '/api/error/',
        ]
    })


def list_users(request):
    """List all users with database simulation"""
    client = tracekit.get_client()

    # Simulate database query
    span = client.start_span('db.query.users', {
        'db.system': 'postgresql',
        'db.operation': 'SELECT',
        'db.table': 'users'
    })

    # Simulate query
    time.sleep(0.05)
    users = [
        {'id': 1, 'name': 'Alice', 'email': 'alice@example.com'},
        {'id': 2, 'name': 'Bob', 'email': 'bob@example.com'},
        {'id': 3, 'name': 'Charlie', 'email': 'charlie@example.com'}
    ]

    client.end_span(span, {'db.rows': len(users)})

    return JsonResponse({'users': users})


def get_user(request, user_id):
    """Get a specific user"""
    client = tracekit.get_client()

    # Capture snapshot for debugging
    client.capture_snapshot('get-user', {
        'user_id': user_id,
        'request_path': request.path
    })

    # Simulate database query
    span = client.start_span('db.query.user', {
        'db.system': 'postgresql',
        'db.operation': 'SELECT',
        'db.table': 'users',
        'user.id': user_id
    })

    time.sleep(0.03)

    if user_id > 10:
        client.end_span(span, {'user.found': False})
        return JsonResponse({'error': 'User not found'}, status=404)

    user = {'id': user_id, 'name': f'User {user_id}', 'email': f'user{user_id}@example.com'}
    client.end_span(span, {'user.found': True})

    return JsonResponse({'user': user})


def slow_endpoint(request):
    """Simulate a slow endpoint"""
    client = tracekit.get_client()

    # Create a custom span for slow operation
    span = client.start_span('slow-operation', {
        'operation.type': 'computation'
    })

    # Simulate slow work
    time.sleep(2)

    client.end_span(span, {
        'operation.duration': 2000
    })

    return JsonResponse({'message': 'This was slow'})


def error_endpoint(request):
    """Endpoint that throws an error"""
    # This error will be automatically captured by TraceKit
    raise Exception('This is a test error!')


@require_http_methods(["POST"])
def checkout(request):
    """Simulate checkout with code monitoring"""
    import json
    client = tracekit.get_client()

    data = json.loads(request.body)

    # Capture snapshot at validation
    client.capture_snapshot('checkout-validation', {
        'user_id': data.get('user_id'),
        'cart_items': len(data.get('items', [])),
        'total_amount': data.get('total', 0)
    })

    # Simulate payment processing
    span = client.start_span('process-payment', {
        'payment.amount': data.get('total'),
        'user.id': data.get('user_id')
    })

    time.sleep(0.5)

    result = {
        'payment_id': 'pay_12345',
        'status': 'success',
        'amount': data.get('total')
    }

    client.end_span(span, {
        'payment.status': result['status'],
        'payment.id': result['payment_id']
    })

    # Capture snapshot at completion
    client.capture_snapshot('checkout-complete', {
        'user_id': data.get('user_id'),
        'payment_id': result['payment_id'],
        'status': result['status']
    })

    return JsonResponse(result)
```

### 4. Configure URLs

```python
# myapp/urls.py

from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('api/users/', views.list_users, name='list_users'),
    path('api/users/<int:user_id>/', views.get_user, name='get_user'),
    path('api/slow/', views.slow_endpoint, name='slow'),
    path('api/error/', views.error_endpoint, name='error'),
    path('api/checkout/', views.checkout, name='checkout'),
]
```

## Environment Variables

Create a `.env` file or set these environment variables:

```bash
export TRACEKIT_API_KEY=your-api-key
export ENVIRONMENT=production
export DJANGO_SETTINGS_MODULE=myproject.settings
```

## Running the Application

```bash
python manage.py runserver
```

Visit http://localhost:8000 to see the application running with TraceKit APM!

## Features Demonstrated

1. **Automatic Request Tracing** - All HTTP requests are automatically traced
2. **Database Query Tracing** - Manual span creation for database operations
3. **Error Tracking** - Exceptions are automatically captured
4. **Code Monitoring** - Breakpoint snapshots for debugging
5. **Custom Spans** - Manual instrumentation for business logic
