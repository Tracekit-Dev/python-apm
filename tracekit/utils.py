"""
Utility functions for TraceKit APM
"""

from typing import Optional


def extract_client_ip_from_headers(headers: dict, remote_addr: Optional[str] = None) -> Optional[str]:
    """
    Extract client IP address from HTTP request headers.

    Checks X-Forwarded-For, X-Real-IP headers (for proxied requests)
    and falls back to remote address.

    This function is automatically used by TraceKit middleware to add
    client IP to all traces for DDoS detection and traffic analysis.

    Args:
        headers: Dictionary of HTTP headers (case-insensitive keys)
        remote_addr: Remote address from direct connection

    Returns:
        Client IP address or None if not found

    Examples:
        >>> headers = {"x-forwarded-for": "203.0.113.1, 198.51.100.1"}
        >>> extract_client_ip_from_headers(headers)
        '203.0.113.1'

        >>> headers = {"x-real-ip": "203.0.113.1"}
        >>> extract_client_ip_from_headers(headers)
        '203.0.113.1'

        >>> extract_client_ip_from_headers({}, "198.51.100.1")
        '198.51.100.1'
    """
    # Normalize headers to lowercase for case-insensitive lookup
    normalized_headers = {k.lower(): v for k, v in headers.items()}

    # Check X-Forwarded-For header (for requests behind proxy/load balancer)
    # Format: "client, proxy1, proxy2"
    x_forwarded_for = normalized_headers.get("x-forwarded-for")
    if x_forwarded_for:
        # Take the first IP (the client)
        ips = x_forwarded_for.split(",")
        if ips:
            return ips[0].strip()

    # Check X-Real-IP header (alternative proxy header)
    x_real_ip = normalized_headers.get("x-real-ip")
    if x_real_ip:
        return x_real_ip.strip()

    # Fallback to remote address (direct connection)
    return remote_addr
