"""
Flask Example with TraceKit APM

This example demonstrates how to use TraceKit APM with Flask.

Usage:
    pip install tracekit-apm[flask]
    export TRACEKIT_API_KEY=your-api-key
    python flask_example.py
"""

import os
import time
from flask import Flask, jsonify, request

import tracekit
from tracekit.middleware.flask import init_flask_app

# Create Flask app
app = Flask(__name__)

# Initialize TraceKit
client = tracekit.init(
    api_key=os.getenv('TRACEKIT_API_KEY', 'demo-key'),
    service_name='flask-example',
    enable_code_monitoring=True  # Enable live debugging
)

# Add TraceKit middleware
init_flask_app(app, client)


# Routes

@app.route('/')
def index():
    """Simple homepage"""
    return jsonify({
        'message': 'Welcome to TraceKit Flask Example',
        'endpoints': [
            '/',
            '/api/users',
            '/api/users/<id>',
            '/api/slow',
            '/api/error'
        ]
    })


@app.route('/api/users')
def list_users():
    """List all users with database simulation"""
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

    return jsonify(users)


@app.route('/api/users/<int:user_id>')
def get_user(user_id):
    """Get a specific user"""
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
        return jsonify({'error': 'User not found'}), 404

    user = {'id': user_id, 'name': f'User {user_id}', 'email': f'user{user_id}@example.com'}
    client.end_span(span, {'user.found': True})

    return jsonify(user)


@app.route('/api/slow')
def slow_endpoint():
    """Simulate a slow endpoint"""
    # Create a custom span for slow operation
    span = client.start_span('slow-operation', {
        'operation.type': 'computation'
    })

    # Simulate slow work
    time.sleep(2)

    client.end_span(span, {
        'operation.duration': 2000
    })

    return jsonify({'message': 'This was slow'})


@app.route('/api/error')
def error_endpoint():
    """Endpoint that throws an error"""
    # This error will be automatically captured by TraceKit
    raise Exception('This is a test error!')


@app.route('/api/checkout', methods=['POST'])
def checkout():
    """Simulate checkout with code monitoring"""
    data = request.get_json()

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

    return jsonify(result)


if __name__ == '__main__':
    print("Starting Flask app with TraceKit APM...")
    print(f"Service: flask-example")
    print("Visit http://localhost:5000")
    app.run(debug=False, port=5000)
