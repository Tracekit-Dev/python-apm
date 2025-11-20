"""
Simple test example to verify TraceKit Python SDK functionality

This is a minimal example to test that the SDK imports and initializes correctly.

Usage:
    pip install -e .
    export TRACEKIT_API_KEY=demo-key
    python test_example.py
"""

import os
import time
import tracekit

def main():
    print("=" * 60)
    print("TraceKit Python SDK - Test Example")
    print("=" * 60)

    # Initialize TraceKit
    print("\n1. Initializing TraceKit...")
    client = tracekit.init(
        api_key=os.getenv('TRACEKIT_API_KEY', 'demo-key'),
        service_name='python-sdk-test',
        enable_code_monitoring=True
    )
    print(f"   ✓ TraceKit initialized for service: python-sdk-test")
    print(f"   ✓ Code monitoring: enabled")

    # Test basic tracing
    print("\n2. Testing basic tracing...")
    span = client.start_trace('test-operation', {
        'test.attribute': 'test-value',
        'test.number': 42
    })
    time.sleep(0.1)
    client.end_span(span, {
        'test.result': 'success'
    })
    print("   ✓ Created and ended a test span")

    # Test nested spans
    print("\n3. Testing nested spans...")
    parent_span = client.start_trace('parent-operation')

    child_span = client.start_span('child-operation', {
        'child.id': 1
    })
    time.sleep(0.05)
    client.end_span(child_span)

    child_span2 = client.start_span('child-operation-2', {
        'child.id': 2
    })
    time.sleep(0.05)
    client.end_span(child_span2)

    client.end_span(parent_span)
    print("   ✓ Created parent span with 2 child spans")

    # Test error recording
    print("\n4. Testing error recording...")
    error_span = client.start_trace('error-operation')
    try:
        raise ValueError("This is a test error")
    except Exception as e:
        client.record_exception(error_span, e)
        client.end_span(error_span, {}, status='ERROR')
        print("   ✓ Recorded test exception on span")

    # Test snapshot capture (code monitoring)
    print("\n5. Testing code monitoring...")
    test_variables = {
        'user_id': 123,
        'order_total': 99.99,
        'items_count': 5
    }

    # Note: This will try to auto-register a breakpoint
    # In a real scenario, this would communicate with the TraceKit backend
    print("   ⚠  Snapshot capture requires TraceKit backend connection")
    print("   ⚠  Skipping snapshot test in offline mode")

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    print("✓ SDK initialization")
    print("✓ Basic span creation")
    print("✓ Nested span hierarchy")
    print("✓ Exception recording")
    print("⚠ Code monitoring (requires backend)")
    print("\n✅ All core functionality working!")
    print("\nNext steps:")
    print("  1. Set TRACEKIT_API_KEY environment variable")
    print("  2. Run one of the framework examples:")
    print("     - python examples/flask_example.py")
    print("     - uvicorn examples.fastapi_example:app")
    print("  3. Visit TraceKit dashboard to see traces")
    print("=" * 60)


if __name__ == '__main__':
    main()
