# TraceKit Service Discovery: Blog Information

## What is Service Discovery?

Service Discovery is a powerful feature in TraceKit APM that **automatically maps dependencies between microservices** in distributed systems. When your services communicate via HTTP, TraceKit captures these interactions and builds a visual service dependency graph - all with zero configuration.

## The Problem It Solves

In modern microservices architectures, understanding service dependencies is critical but challenging:

- **Visibility Gap**: Teams often don't know which services depend on which
- **Debugging Difficulty**: When something breaks, tracing the root cause across services is time-consuming
- **Documentation Drift**: Architecture diagrams become outdated as systems evolve
- **Performance Bottlenecks**: It's hard to identify which service calls are slowing down requests

TraceKit's Service Discovery solves all of these problems automatically.

## How It Works

### The Magic Behind the Scenes

1. **Automatic HTTP Client Instrumentation**: When your service makes an outgoing HTTP request, TraceKit automatically creates a CLIENT span
2. **W3C Trace Context Propagation**: The `traceparent` header is injected into every outgoing request, linking the caller to the callee
3. **Intelligent Service Name Detection**: TraceKit extracts meaningful service names from URLs (e.g., `http://payment-service:3000` becomes `payment-service`)
4. **Dependency Graph Construction**: The backend aggregates all CLIENT and SERVER spans to build a real-time service map

### Zero Configuration Required

```javascript
// Node.js - Just use fetch or axios as normal
const response = await fetch('http://payment-service/charge', {
  method: 'POST',
  body: JSON.stringify({ amount: 99.99 })
});
// TraceKit automatically:
// - Creates a CLIENT span
// - Injects traceparent header
// - Maps the dependency to payment-service
```

```python
# Python - Use requests or httpx as normal
import requests
response = requests.post('http://inventory-service/reserve', json={'item_id': 123})
# Same automatic instrumentation!
```

```php
// Laravel - Use the HTTP facade
use Illuminate\Support\Facades\Http;
$response = Http::post('http://user-service/validate', ['user_id' => $userId]);
// Automatically traced!
```

```go
// Go - Use the standard http.Client with TraceKit's wrapper
resp, err := sdk.HTTPClient().Post("http://notification-service/send", "application/json", body)
// Full distributed tracing!
```

## Key Features

### 1. Automatic CLIENT Span Creation
Every outgoing HTTP request becomes a CLIENT span with:
- Target URL and HTTP method
- Response status code
- Request duration
- `peer.service` attribute identifying the target service

### 2. Intelligent Service Name Extraction

| URL Pattern | Extracted Service Name |
|-------------|------------------------|
| `http://payment-service:3000` | `payment-service` |
| `http://payment.internal` | `payment` |
| `http://payment.svc.cluster.local` | `payment` |
| `https://api.stripe.com` | `api.stripe.com` |

Works seamlessly with:
- Kubernetes service names
- Docker Compose services
- Internal DNS
- External APIs

### 3. Custom Service Name Mappings
For local development or complex networking setups:

```javascript
// Node.js
const tracekit = require('@tracekit/node-apm');
tracekit.init({
  apiKey: process.env.TRACEKIT_API_KEY,
  serviceName: 'checkout-service',
  serviceNameMappings: {
    'localhost:8082': 'payment-service',
    'localhost:8083': 'inventory-service',
    'localhost:8084': 'user-service'
  }
});
```

### 4. Visual Service Map
The TraceKit dashboard provides:
- **Interactive Service Graph**: Visual representation of all service dependencies
- **Health Metrics**: Error rates, latency percentiles for each service
- **Dependency Analysis**: See upstream and downstream services at a glance
- **Request Flow**: Trace individual requests across multiple services

## Supported Languages & Frameworks

| Language | Framework | HTTP Client | Status |
|----------|-----------|-------------|--------|
| **Node.js** | Express, NestJS | fetch, axios, http | Automatic |
| **Python** | FastAPI, Django, Flask | requests, httpx, aiohttp | Automatic |
| **Go** | net/http, Gin, Echo | http.Client (wrapped) | Automatic |
| **PHP** | Native | Guzzle, cURL | Automatic |
| **Laravel** | Laravel 10, 11, 12 | HTTP Facade, Guzzle | Automatic |

## Real-World Use Case: E-Commerce Checkout

Imagine an e-commerce checkout flow:

```
User Request
    |
    v
[Checkout Service] --> [Payment Service]
    |                       |
    |                       v
    |               [Fraud Detection]
    v
[Inventory Service] --> [Warehouse API]
    |
    v
[Notification Service] --> [Email Provider]
```

With TraceKit Service Discovery:
1. A single request to `/checkout` generates a complete trace
2. You see exactly which services were called and in what order
3. If payment fails, you immediately see the error in the Payment Service span
4. Latency breakdown shows Fraud Detection added 200ms to the request

## Benefits for Development Teams

### For Developers
- **Faster Debugging**: Trace requests across services in seconds
- **Code Confidence**: Understand the impact of changes before deploying
- **No Manual Instrumentation**: Focus on features, not observability code

### For DevOps/SRE
- **Real-time Architecture Documentation**: Always up-to-date service map
- **Incident Response**: Quickly identify failing dependencies
- **Capacity Planning**: Understand traffic patterns between services

### For Engineering Managers
- **System Understanding**: Visualize your entire architecture
- **Risk Assessment**: Identify critical paths and single points of failure
- **Team Communication**: Shared language for discussing system architecture

## Getting Started

### Node.js
```bash
npm install @tracekit/node-apm
```

```javascript
require('@tracekit/node-apm').init({
  apiKey: process.env.TRACEKIT_API_KEY,
  serviceName: 'my-service'
});
```

### Python
```bash
pip install tracekit-apm
```

```python
from tracekit import TraceKitSDK
sdk = TraceKitSDK(
    api_key=os.getenv('TRACEKIT_API_KEY'),
    service_name='my-service'
)
```

### Laravel
```bash
composer require tracekit/laravel-apm
php artisan tracekit:install
```

### Go
```bash
go get github.com/tracekit/go-apm
```

```go
sdk, _ := tracekit.NewSDK(&tracekit.Config{
    APIKey:      os.Getenv("TRACEKIT_API_KEY"),
    ServiceName: "my-service",
})
```

## Performance Impact

- **< 5% overhead** on average request time
- **Asynchronous trace export**: Doesn't block responses
- **Configurable sampling**: For high-traffic applications
- **Lightweight SDK**: Minimal memory footprint

## Comparison with Alternatives

| Feature | TraceKit | DataDog | New Relic | Jaeger |
|---------|----------|---------|-----------|--------|
| Zero-config HTTP instrumentation | Yes | Partial | Partial | No |
| Automatic service mapping | Yes | Yes | Yes | Manual |
| Service name from URL | Yes | Limited | Limited | No |
| Custom service mappings | Yes | No | No | No |
| Open source SDKs | Yes | No | No | Yes |
| Self-hostable | Coming | No | No | Yes |

## Quotes for the Blog

> "Service Discovery transformed how we debug production issues. What used to take hours now takes minutes." - *Potential customer testimonial*

> "The automatic service mapping means our architecture documentation is always accurate - it updates itself!" - *Potential customer testimonial*

## Key Takeaways for the Blog

1. **Zero Configuration**: Works out of the box with any HTTP client
2. **Language Agnostic**: Same great experience across Node.js, Python, Go, PHP, and Laravel
3. **Intelligent Detection**: Automatically extracts meaningful service names
4. **Real-time Visibility**: See your service dependencies as they happen
5. **Developer-First**: Built by developers, for developers

## Technical Deep-Dive Topics

For a more technical blog, consider covering:

1. **W3C Trace Context Standard**: How `traceparent` header enables distributed tracing
2. **OpenTelemetry Foundation**: TraceKit is built on OpenTelemetry standards
3. **Span Types**: The difference between CLIENT and SERVER spans
4. **Context Propagation**: How trace context flows between services
5. **Sampling Strategies**: Head-based vs tail-based sampling

## Resources

- **Documentation**: https://app.tracekit.dev/docs
- **GitHub**: https://github.com/Tracekit-Dev
- **npm**: https://www.npmjs.com/package/@tracekit/node-apm
- **PyPI**: https://pypi.org/project/tracekit-apm/
- **Packagist**: https://packagist.org/packages/tracekit/laravel-apm

---

## Twitter/X Threads & Tweets

### Launch Announcement Thread

**Tweet 1 (Hook):**
```
Just shipped: Automatic Service Discovery for distributed systems.

Zero config. Zero code changes. Just... works.

Your microservices architecture, visualized in real-time.

Here's how it works: 🧵
```

**Tweet 2:**
```
The problem:

In microservices, understanding dependencies is HARD.

- Which service calls which?
- Where's the bottleneck?
- Why did this request fail?

Architecture diagrams are always outdated.

TraceKit Service Discovery solves this automatically.
```

**Tweet 3:**
```
How it works:

1. Install the SDK (one line)
2. Make HTTP calls like normal
3. TraceKit automatically:
   - Creates CLIENT spans
   - Injects W3C trace headers
   - Maps service dependencies

No manual instrumentation needed.
```

**Tweet 4:**
```
Smart service name detection:

http://payment-service:3000 → payment-service
http://api.stripe.com → api.stripe.com
http://user.svc.cluster.local → user

Works with Kubernetes, Docker Compose, internal DNS, external APIs.
```

**Tweet 5:**
```
Works across your entire stack:

- Node.js (Express, NestJS)
- Python (FastAPI, Django, Flask)
- Go (net/http, Gin, Echo)
- PHP (native)
- Laravel (10, 11, 12)

Same experience. Same dashboard. All connected.
```

**Tweet 6 (CTA):**
```
Try it now:

npm install @tracekit/node-apm
pip install tracekit-apm
composer require tracekit/laravel-apm
go get github.com/tracekit/go-apm

Free tier available. Start tracing in 5 minutes.

https://tracekit.dev
```

---

### Standalone Tweets

**Problem/Solution:**
```
Debugging microservices without distributed tracing is like debugging a monolith without stack traces.

TraceKit Service Discovery: automatic dependency mapping for your entire architecture.

Zero config required.
```

**Developer Experience:**
```
Before: "Which service called the payment API?"
*checks 5 different logs*
*asks 3 teams*
*still not sure*

After: One click in TraceKit. Full request trace. Every service call visible.

That's Service Discovery.
```

**Technical Flex:**
```
We built automatic HTTP client instrumentation for:
- fetch/axios (Node.js)
- requests/httpx/aiohttp (Python)
- http.Client (Go)
- Guzzle/cURL (PHP)
- HTTP facade (Laravel)

All using W3C Trace Context (traceparent header).

Standards-based. Interoperable. Production-ready.
```

**Pain Point:**
```
"Our architecture diagram is outdated"

Every team ever.

What if your architecture diagram updated itself... automatically... in real-time?

That's what TraceKit Service Discovery does.
```

**Comparison:**
```
Setting up distributed tracing:

❌ Manual: 2 weeks, custom code everywhere
❌ Other APMs: Proprietary agents, complex config
✅ TraceKit: npm install, add API key, done

Your time is valuable. Stop writing instrumentation code.
```

**Use Case:**
```
Checkout request taking 3 seconds?

TraceKit shows:
- Checkout service: 50ms
- Payment service: 200ms
- Fraud detection: 2.5s ← found it
- Inventory: 100ms

Fix the right service. Ship faster.
```

**Quick Win:**
```
Add this to any Node.js app:

require('@tracekit/node-apm').init({
  apiKey: process.env.TRACEKIT_API_KEY,
  serviceName: 'my-service'
});

Every HTTP call is now traced.
Every dependency is mapped.
Zero code changes needed.
```

---

### LinkedIn Post

```
Excited to announce Service Discovery for TraceKit APM!

In microservices architectures, understanding service dependencies is critical but challenging. Teams struggle with:

📍 Which services depend on which?
📍 Where are the performance bottlenecks?
📍 Why did this request fail across services?

Traditional solutions require manual instrumentation, complex configuration, or expensive enterprise tools.

TraceKit Service Discovery changes this:

✅ Zero configuration required
✅ Automatic HTTP client instrumentation
✅ Works across Node.js, Python, Go, PHP, and Laravel
✅ Real-time service dependency graphs
✅ Built on open standards (W3C Trace Context, OpenTelemetry)

Simply install the SDK and your architecture documentation updates itself.

Try it free: https://tracekit.dev

#Observability #Microservices #DevOps #APM #DistributedTracing
```

---

*Last Updated: November 21, 2025*
