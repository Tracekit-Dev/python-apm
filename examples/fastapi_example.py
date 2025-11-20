"""
FastAPI Example with TraceKit APM

This example demonstrates how to use TraceKit APM with FastAPI.

Usage:
    pip install tracekit-apm[fastapi]
    export TRACEKIT_API_KEY=your-api-key
    uvicorn fastapi_example:app --reload
"""

import os
import asyncio
from typing import List, Optional
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException

import tracekit
from tracekit.middleware.fastapi import init_fastapi_app

# Create FastAPI app
app = FastAPI(
    title="TraceKit FastAPI Example",
    description="Example FastAPI app with TraceKit APM",
    version="1.0.0"
)

# Initialize TraceKit
client = tracekit.init(
    api_key=os.getenv('TRACEKIT_API_KEY', 'demo-key'),
    service_name='fastapi-example',
    enable_code_monitoring=True  # Enable live debugging
)

# Add TraceKit middleware
init_fastapi_app(app, client)


# Models

class User(BaseModel):
    id: int
    name: str
    email: str


class CheckoutRequest(BaseModel):
    user_id: int
    items: List[dict]
    total: float


class CheckoutResponse(BaseModel):
    payment_id: str
    status: str
    amount: float


# Routes

@app.get("/")
async def root():
    """Simple homepage"""
    return {
        "message": "Welcome to TraceKit FastAPI Example",
        "endpoints": [
            "/",
            "/api/users",
            "/api/users/{user_id}",
            "/api/slow",
            "/api/error",
            "/api/checkout"
        ]
    }


@app.get("/api/users", response_model=List[User])
async def list_users():
    """List all users with database simulation"""
    # Simulate database query
    span = client.start_span('db.query.users', {
        'db.system': 'postgresql',
        'db.operation': 'SELECT',
        'db.table': 'users'
    })

    # Simulate async query
    await asyncio.sleep(0.05)
    users = [
        User(id=1, name='Alice', email='alice@example.com'),
        User(id=2, name='Bob', email='bob@example.com'),
        User(id=3, name='Charlie', email='charlie@example.com')
    ]

    client.end_span(span, {'db.rows': len(users)})

    return users


@app.get("/api/users/{user_id}", response_model=User)
async def get_user(user_id: int):
    """Get a specific user"""
    # Capture snapshot for debugging
    await client.capture_snapshot('get-user', {
        'user_id': user_id,
        'endpoint': '/api/users/{user_id}'
    })

    # Simulate database query
    span = client.start_span('db.query.user', {
        'db.system': 'postgresql',
        'db.operation': 'SELECT',
        'db.table': 'users',
        'user.id': user_id
    })

    await asyncio.sleep(0.03)

    if user_id > 10:
        client.end_span(span, {'user.found': False})
        raise HTTPException(status_code=404, detail='User not found')

    user = User(id=user_id, name=f'User {user_id}', email=f'user{user_id}@example.com')
    client.end_span(span, {'user.found': True})

    return user


@app.get("/api/slow")
async def slow_endpoint():
    """Simulate a slow endpoint"""
    # Create a custom span for slow operation
    span = client.start_span('slow-operation', {
        'operation.type': 'computation'
    })

    # Simulate slow work
    await asyncio.sleep(2)

    client.end_span(span, {
        'operation.duration': 2000
    })

    return {"message": "This was slow"}


@app.get("/api/error")
async def error_endpoint():
    """Endpoint that throws an error"""
    # This error will be automatically captured by TraceKit
    raise Exception('This is a test error!')


@app.post("/api/checkout", response_model=CheckoutResponse)
async def checkout(request: CheckoutRequest):
    """Simulate checkout with code monitoring"""
    # Capture snapshot at validation
    await client.capture_snapshot('checkout-validation', {
        'user_id': request.user_id,
        'cart_items': len(request.items),
        'total_amount': request.total
    })

    # Simulate payment processing
    span = client.start_span('process-payment', {
        'payment.amount': request.total,
        'user.id': request.user_id
    })

    await asyncio.sleep(0.5)

    result = CheckoutResponse(
        payment_id='pay_12345',
        status='success',
        amount=request.total
    )

    client.end_span(span, {
        'payment.status': result.status,
        'payment.id': result.payment_id
    })

    # Capture snapshot at completion
    await client.capture_snapshot('checkout-complete', {
        'user_id': request.user_id,
        'payment_id': result.payment_id,
        'status': result.status
    })

    return result


# Startup/Shutdown Events

@app.on_event("startup")
async def startup_event():
    print("Starting FastAPI app with TraceKit APM...")
    print(f"Service: fastapi-example")
    print("Visit http://localhost:8000")
    print("Docs: http://localhost:8000/docs")


@app.on_event("shutdown")
async def shutdown_event():
    print("Shutting down TraceKit APM...")
    await client.shutdown()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
