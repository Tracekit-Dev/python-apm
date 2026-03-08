"""
Snapshot Client - Code monitoring with breakpoints and variable inspection
"""

import inspect
import json
import re
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict

import requests
from opentelemetry import trace as otel_trace


@dataclass
class BreakpointConfig:
    """Configuration for a breakpoint"""
    id: str
    service_name: str
    file_path: str
    function_name: str
    label: Optional[str]
    line_number: int
    condition: Optional[str]
    max_captures: int
    capture_count: int
    expire_at: Optional[datetime]
    enabled: bool


@dataclass
class SecurityFlag:
    """Security issue found in snapshot variables"""
    type: str
    severity: str
    variable: Optional[str] = None


@dataclass
class Snapshot:
    """Snapshot of code execution state"""
    breakpoint_id: Optional[str]
    service_name: str
    file_path: str
    function_name: str
    label: Optional[str]
    line_number: int
    variables: Dict[str, Any]
    security_flags: Optional[List[Dict[str, Any]]]
    stack_trace: str
    trace_id: Optional[str]
    span_id: Optional[str]
    request_context: Optional[Dict[str, Any]]
    captured_at: datetime


class SnapshotClient:
    """
    Client for code monitoring with breakpoints and snapshots.

    Features:
    - Automatic breakpoint registration
    - Background polling for active breakpoints
    - Variable capture with sanitization
    - Request context extraction
    """

    def __init__(self, api_key: str, base_url: str, service_name: str):
        self.api_key = api_key
        self.base_url = base_url
        self.service_name = service_name
        self.breakpoints_cache: Dict[str, BreakpointConfig] = {}
        self.registration_cache: set = set()
        self.poll_thread: Optional[threading.Thread] = None
        self.stop_polling = False
        self.last_fetch: Optional[datetime] = None

        # Kill switch: server-initiated monitoring disable
        self._kill_switch_active = False

        # SSE (Server-Sent Events) real-time updates
        self._sse_endpoint: Optional[str] = None
        self._sse_active = False
        self._sse_thread: Optional[threading.Thread] = None
        self._sse_stop = False

    def start(self) -> None:
        """Start background polling for active breakpoints."""
        self.fetch_active_breakpoints()  # Immediate fetch

        # Start background thread for polling
        self.stop_polling = False
        self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.poll_thread.start()

        print(f"📸 TraceKit Snapshot Client started for service: {self.service_name}")

    def stop(self) -> None:
        """Stop polling for breakpoints and close SSE connection."""
        self.stop_polling = True
        self._sse_stop = True
        self._sse_active = False
        if self.poll_thread:
            self.poll_thread.join(timeout=5)
        if self._sse_thread:
            self._sse_thread.join(timeout=5)
        print("📸 TraceKit Snapshot Client stopped")

    def _poll_loop(self) -> None:
        """Background polling loop."""
        while not self.stop_polling:
            time.sleep(30)  # Poll every 30 seconds
            if not self.stop_polling:
                # Skip polling when SSE is actively connected
                if self._sse_active:
                    continue
                self.fetch_active_breakpoints()

    def check_and_capture_with_context(
        self,
        label: str,
        variables: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Automatic capture with runtime detection.

        Args:
            label: Label for the snapshot
            variables: Variables to capture
        """
        variables = variables or {}

        # Check kill switch before capturing
        if self._kill_switch_active:
            return

        # Get caller information using inspect
        frame = inspect.currentframe()
        if frame is None or frame.f_back is None or frame.f_back.f_back is None:
            print("⚠️  Could not detect caller location")
            return

        # Get the actual caller (skip this method and the wrapper)
        caller_frame = frame.f_back.f_back
        file_path = caller_frame.f_code.co_filename
        line_number = caller_frame.f_lineno
        function_name = caller_frame.f_code.co_name

        # Check if location is registered
        location_key = f"{function_name}:{label}"

        if location_key not in self.registration_cache:
            # Auto-register breakpoint
            breakpoint = self.auto_register_breakpoint(
                file_path=file_path,
                line_number=line_number,
                function_name=function_name,
                label=label
            )

            if breakpoint:
                self.registration_cache.add(location_key)
                self.breakpoints_cache[location_key] = breakpoint
            else:
                return

        # Check cache for active breakpoint
        breakpoint = self.breakpoints_cache.get(location_key)
        if not breakpoint or not breakpoint.enabled:
            return

        # Check expiration
        if breakpoint.expire_at and datetime.now() > breakpoint.expire_at:
            return

        # Check max captures
        if breakpoint.max_captures > 0 and breakpoint.capture_count >= breakpoint.max_captures:
            return

        # Extract request context
        request_context = self.extract_request_context()

        # Get stack trace
        stack_trace = self._get_stack_trace()

        # Scan variables for security issues
        sanitized_vars, security_flags = self.scan_for_security_issues(variables)

        # Extract trace context from OpenTelemetry
        trace_id = None
        span_id = None
        try:
            current_span = otel_trace.get_current_span()
            span_context = current_span.get_span_context()
            if span_context.is_valid and (span_context.trace_flags & otel_trace.TraceFlags.SAMPLED):
                trace_id = format(span_context.trace_id, '032x')
                span_id = format(span_context.span_id, '016x')
        except Exception:
            pass

        # Create snapshot
        snapshot = Snapshot(
            breakpoint_id=breakpoint.id,
            service_name=self.service_name,
            file_path=file_path,
            function_name=function_name,
            label=label,
            line_number=line_number,
            variables=sanitized_vars,
            security_flags=security_flags,
            stack_trace=stack_trace,
            request_context=request_context,
            trace_id=trace_id,
            span_id=span_id,
            captured_at=datetime.now()
        )

        # Send snapshot
        self.capture_snapshot(snapshot)

    def _get_stack_trace(self) -> str:
        """Get current stack trace as a string."""
        stack = inspect.stack()[3:]  # Skip internal frames
        lines = []
        for frame_info in stack:
            func_name = frame_info.function
            file_path = frame_info.filename
            line_no = frame_info.lineno

            if func_name and func_name != "<module>":
                lines.append(f"{func_name} at {file_path}:{line_no}")
            else:
                lines.append(f"{file_path}:{line_no}")

        return "\n".join(lines)

    def fetch_active_breakpoints(self) -> None:
        """Fetch active breakpoints from backend."""
        try:
            url = f"{self.base_url}/sdk/snapshots/active/{self.service_name}"
            response = requests.get(
                url,
                headers={"X-API-Key": self.api_key},
                timeout=10
            )

            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}")

            data = response.json()
            breakpoints = data.get("breakpoints", [])

            # Handle kill switch state
            kill_switch = data.get("kill_switch", False)
            if kill_switch and not self._kill_switch_active:
                print("TraceKit: Code monitoring disabled by server kill switch.")
            elif not kill_switch and self._kill_switch_active:
                print("TraceKit: Code monitoring re-enabled by server.")
            self._kill_switch_active = kill_switch

            # If kill-switched, close any active SSE connection
            if self._kill_switch_active and self._sse_active:
                self._sse_stop = True
                self._sse_active = False
                print("TraceKit: SSE connection closed due to kill switch")

            # SSE auto-discovery: if sse_endpoint present and not already connected
            sse_endpoint = data.get("sse_endpoint")
            if sse_endpoint and not self._sse_active and not self._kill_switch_active and len(breakpoints) > 0:
                self._sse_endpoint = sse_endpoint
                self._sse_stop = False
                self._sse_thread = threading.Thread(
                    target=self._connect_sse, args=(sse_endpoint,), daemon=True
                )
                self._sse_thread.start()

            self.update_breakpoint_cache(breakpoints)
            self.last_fetch = datetime.now()

        except Exception as e:
            print(f"⚠️  Failed to fetch breakpoints: {e}")

    def _connect_sse(self, endpoint: str) -> None:
        """Connect to SSE endpoint for real-time breakpoint updates.
        Falls back to polling if SSE connection fails or is interrupted.
        Runs in a daemon thread."""
        try:
            full_url = f"{self.base_url}{endpoint}"
            response = requests.get(
                full_url,
                headers={
                    "X-API-Key": self.api_key,
                    "Accept": "text/event-stream",
                },
                stream=True,
                timeout=(10, None),  # 10s connect timeout, no read timeout
            )

            if response.status_code != 200:
                print(f"TraceKit: SSE endpoint returned {response.status_code}, falling back to polling")
                self._sse_active = False
                return

            self._sse_active = True
            print("TraceKit: SSE connection established for real-time breakpoint updates")

            event_type = ""
            data_buffer = ""

            for line_bytes in response.iter_lines(decode_unicode=True):
                if self._sse_stop:
                    break

                if line_bytes is None:
                    continue

                line = line_bytes if isinstance(line_bytes, str) else line_bytes.decode("utf-8", errors="replace")

                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:"):
                    if data_buffer:
                        data_buffer += "\n"
                    data_buffer += line[5:].strip()
                elif line == "":
                    # Empty line = event boundary
                    if event_type and data_buffer:
                        self._handle_sse_event(event_type, data_buffer)
                    event_type = ""
                    data_buffer = ""

            print("TraceKit: SSE connection closed, falling back to polling")

        except BaseException as e:
            # Crash isolation: never let SSE bugs crash the host application
            print(f"TraceKit: SSE connection lost, falling back to polling: {e}")
        finally:
            self._sse_active = False

    def _handle_sse_event(self, event_type: str, data: str) -> None:
        """Process a single SSE event."""
        try:
            if event_type == "init":
                init_data = json.loads(data)
                breakpoints = init_data.get("breakpoints", [])
                self.update_breakpoint_cache(breakpoints)
                self._kill_switch_active = init_data.get("kill_switch", False)
                if self._kill_switch_active:
                    self._sse_stop = True
                print(f"TraceKit: SSE init received, {len(breakpoints)} breakpoints loaded")

            elif event_type in ("breakpoint_created", "breakpoint_updated"):
                bp_data = json.loads(data)
                bp = BreakpointConfig(
                    id=bp_data["id"],
                    service_name=self.service_name,
                    file_path=bp_data["file_path"],
                    function_name=bp_data.get("function_name", ""),
                    label=bp_data.get("label"),
                    line_number=bp_data["line_number"],
                    condition=bp_data.get("condition"),
                    max_captures=bp_data.get("max_captures", 100),
                    capture_count=bp_data.get("capture_count", 0),
                    expire_at=datetime.fromisoformat(bp_data["expire_at"]) if bp_data.get("expire_at") else None,
                    enabled=bp_data.get("enabled", True),
                )
                # Upsert by label key and line key
                if bp.label and bp.function_name:
                    label_key = f"{bp.function_name}:{bp.label}"
                    self.breakpoints_cache[label_key] = bp
                line_key = f"{bp.file_path}:{bp.line_number}"
                self.breakpoints_cache[line_key] = bp
                print(f"TraceKit: SSE breakpoint {event_type}: {bp.id}")

            elif event_type == "breakpoint_deleted":
                delete_data = json.loads(data)
                bp_id = delete_data["id"]
                keys_to_delete = [
                    key for key, bp in self.breakpoints_cache.items() if bp.id == bp_id
                ]
                for key in keys_to_delete:
                    del self.breakpoints_cache[key]
                print(f"TraceKit: SSE breakpoint deleted: {bp_id}")

            elif event_type == "kill_switch":
                ks_data = json.loads(data)
                self._kill_switch_active = ks_data.get("enabled", False)
                if self._kill_switch_active:
                    print("TraceKit: Kill switch enabled via SSE, closing connection")
                    self._sse_stop = True

            elif event_type == "heartbeat":
                pass  # No action needed -- keeps connection alive

            else:
                print(f"TraceKit: unknown SSE event type: {event_type}")

        except BaseException as e:
            print(f"TraceKit: error handling SSE event {event_type}: {e}")

    def update_breakpoint_cache(self, breakpoints: List[Dict[str, Any]]) -> None:
        """Update in-memory cache of breakpoints."""
        self.breakpoints_cache.clear()

        for bp_data in breakpoints:
            # Convert to BreakpointConfig
            # Note: service_name comes from self.service_name, not the API response
            bp = BreakpointConfig(
                id=bp_data["id"],
                service_name=self.service_name,
                file_path=bp_data["file_path"],
                function_name=bp_data.get("function_name", ""),
                label=bp_data.get("label"),
                line_number=bp_data["line_number"],
                condition=bp_data.get("condition"),
                max_captures=bp_data.get("max_captures", 100),
                capture_count=bp_data.get("capture_count", 0),
                expire_at=datetime.fromisoformat(bp_data["expire_at"]) if bp_data.get("expire_at") else None,
                enabled=bp_data.get("enabled", True)
            )

            # Primary key: function + label
            if bp.label and bp.function_name:
                label_key = f"{bp.function_name}:{bp.label}"
                self.breakpoints_cache[label_key] = bp

            # Secondary key: file + line
            line_key = f"{bp.file_path}:{bp.line_number}"
            self.breakpoints_cache[line_key] = bp

        if breakpoints:
            print(f"📸 Updated breakpoint cache: {len(breakpoints)} active breakpoints")

    def auto_register_breakpoint(
        self,
        file_path: str,
        line_number: int,
        function_name: str,
        label: str
    ) -> Optional[BreakpointConfig]:
        """Auto-register a breakpoint with the backend."""
        try:
            response = requests.post(
                f"{self.base_url}/sdk/snapshots/auto-register",
                headers={
                    "X-API-Key": self.api_key,
                    "Content-Type": "application/json"
                },
                json={
                    "service_name": self.service_name,
                    "file_path": file_path,
                    "line_number": line_number,
                    "function_name": function_name,
                    "label": label
                },
                timeout=10
            )

            if response.status_code not in [200, 201]:
                print(f"⚠️  Failed to auto-register breakpoint: {response.status_code}")
                return None

            data = response.json()
            # Backend returns just {"id": "..."} for both new and existing breakpoints
            if "id" in data:
                return BreakpointConfig(
                    id=data["id"],
                    service_name=self.service_name,
                    file_path=file_path,
                    function_name=function_name,
                    label=label,
                    line_number=line_number,
                    condition=None,
                    max_captures=100,
                    capture_count=0,
                    expire_at=None,
                    enabled=True
                )

            return None

        except Exception as e:
            print(f"⚠️  Failed to auto-register breakpoint: {e}")
            return None

    def capture_snapshot(self, snapshot: Snapshot) -> None:
        """Capture and send snapshot to backend."""
        try:
            # Convert snapshot to dict
            snapshot_dict = asdict(snapshot)

            # Convert datetime to RFC3339 format with timezone (required by Go backend)
            if snapshot_dict["captured_at"]:
                # Replace naive datetime with timezone-aware UTC datetime
                if snapshot_dict["captured_at"].tzinfo is None:
                    from datetime import timezone
                    snapshot_dict["captured_at"] = snapshot_dict["captured_at"].replace(tzinfo=timezone.utc)
                # Format as RFC3339 with 'Z' suffix for UTC
                snapshot_dict["captured_at"] = snapshot_dict["captured_at"].strftime("%Y-%m-%dT%H:%M:%S.%fZ")

            response = requests.post(
                f"{self.base_url}/sdk/snapshots/capture",
                headers={
                    "X-API-Key": self.api_key,
                    "Content-Type": "application/json"
                },
                json=snapshot_dict,
                timeout=10
            )

            if response.status_code not in [200, 201]:
                print(f"⚠️  Failed to capture snapshot: {response.status_code} - {response.text}")
            else:
                print(f"📸 Snapshot captured: {snapshot.label or snapshot.file_path}")

        except Exception as e:
            print(f"⚠️  Failed to capture snapshot: {e}")

    def extract_request_context(self) -> Optional[Dict[str, Any]]:
        """
        Extract request context from the current execution context.

        This would need to be implemented per-framework in middleware.
        For now, returns None.
        """
        # TODO: Extract from contextvars or thread-local storage
        return None

    def sanitize_variables(
        self,
        variables: Dict[str, Any],
        max_depth: int = 3,
        max_string_length: int = 1000
    ) -> Dict[str, Any]:
        """
        Sanitize variables for JSON serialization.

        Args:
            variables: Variables to sanitize
            max_depth: Maximum nesting depth for objects/lists
            max_string_length: Maximum string length before truncation

        Returns:
            Sanitized variables dictionary
        """
        def sanitize_value(value: Any, depth: int = 0) -> Any:
            if depth > max_depth:
                return f"[max depth {max_depth} reached]"

            if isinstance(value, str):
                if len(value) > max_string_length:
                    return value[:max_string_length] + "..."
                return value

            elif isinstance(value, (int, float, bool, type(None))):
                return value

            elif isinstance(value, (list, tuple)):
                return [sanitize_value(v, depth + 1) for v in value[:10]]  # Limit to 10 items

            elif isinstance(value, dict):
                return {
                    k: sanitize_value(v, depth + 1)
                    for k, v in list(value.items())[:20]  # Limit to 20 keys
                }

            else:
                try:
                    # Try to serialize
                    json.dumps(value)
                    return value
                except (TypeError, ValueError):
                    return f"[{type(value).__name__}]"

        sanitized = {}
        for key, value in variables.items():
            try:
                sanitized[key] = sanitize_value(value)
            except Exception:
                sanitized[key] = f"[{type(value).__name__}]"

        return sanitized

    def scan_for_security_issues(
        self,
        variables: Dict[str, Any]
    ) -> tuple[Dict[str, Any], Optional[List[Dict[str, Any]]]]:
        """
        Scan variables for sensitive data and return sanitized variables with security flags.

        Args:
            variables: Variables to scan

        Returns:
            Tuple of (sanitized_variables, security_flags)
        """
        # Sensitive data patterns
        sensitive_patterns = {
            'password': re.compile(r'(?i)(password|passwd|pwd)\s*[=:]\s*["\']?[^\s"\']{6,}'),
            'api_key': re.compile(r'(?i)(api[_-]?key|apikey)\s*[=:]\s*["\']?[A-Za-z0-9_-]{20,}'),
            'jwt': re.compile(r'eyJ[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*'),
            'credit_card': re.compile(r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14})\b'),
        }

        # Letter-boundary pattern -- avoids matching substrings like "monkey" or "turkey"
        sensitive_name_pattern = re.compile(r'(?i)(?:^|[^a-zA-Z])(password|passwd|pwd|secret|token|key|credential|api_key|apikey)(?:[^a-zA-Z]|$)')

        security_flags = []
        sanitized = self.sanitize_variables(variables)

        # Scan variable names and values
        for name, value in variables.items():
            # Check variable name for sensitive patterns
            if sensitive_name_pattern.search(name):
                security_flags.append({
                    'type': 'sensitive_variable_name',
                    'severity': 'medium',
                    'variable': name
                })
                sanitized[name] = '[REDACTED]'
                continue

            # Check variable value for sensitive data
            try:
                serialized = json.dumps(value)
                for data_type, pattern in sensitive_patterns.items():
                    if pattern.search(serialized):
                        security_flags.append({
                            'type': f'sensitive_data_{data_type}',
                            'severity': 'high',
                            'variable': name
                        })
                        sanitized[name] = '[REDACTED]'
                        break
            except (TypeError, ValueError):
                # If value can't be serialized, keep sanitized version
                pass

        return sanitized, security_flags if security_flags else None
