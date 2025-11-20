"""
Snapshot Client - Code monitoring with breakpoints and variable inspection
"""

import inspect
import json
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict

import requests


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
class Snapshot:
    """Snapshot of code execution state"""
    breakpoint_id: Optional[str]
    service_name: str
    file_path: str
    function_name: str
    label: Optional[str]
    line_number: int
    variables: Dict[str, Any]
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

    def start(self) -> None:
        """Start background polling for active breakpoints."""
        self.fetch_active_breakpoints()  # Immediate fetch

        # Start background thread for polling
        self.stop_polling = False
        self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.poll_thread.start()

        print(f"📸 TraceKit Snapshot Client started for service: {self.service_name}")

    def stop(self) -> None:
        """Stop polling for breakpoints."""
        self.stop_polling = True
        if self.poll_thread:
            self.poll_thread.join(timeout=5)
        print("📸 TraceKit Snapshot Client stopped")

    def _poll_loop(self) -> None:
        """Background polling loop."""
        while not self.stop_polling:
            time.sleep(30)  # Poll every 30 seconds
            if not self.stop_polling:
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

        # Create snapshot
        snapshot = Snapshot(
            breakpoint_id=breakpoint.id,
            service_name=self.service_name,
            file_path=file_path,
            function_name=function_name,
            label=label,
            line_number=line_number,
            variables=self.sanitize_variables(variables),
            stack_trace=stack_trace,
            request_context=request_context,
            trace_id=None,  # TODO: Extract from OpenTelemetry context
            span_id=None,   # TODO: Extract from OpenTelemetry context
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
            self.update_breakpoint_cache(breakpoints)
            self.last_fetch = datetime.now()

        except Exception as e:
            print(f"⚠️  Failed to fetch breakpoints: {e}")

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
