"""
TraceKit LLM Common Helpers

Shared configuration, span attribute helpers, and PII scrubbing for LLM integrations.
Follows OTel GenAI Semantic Conventions (v1.40.0).
"""

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from opentelemetry.trace import Span, Status, StatusCode


# PII pattern using letter-based boundaries (NOT \b which treats _ as word char)
_PII_PATTERN = re.compile(
    r'(?:^|[^a-zA-Z])(password|passwd|pwd|secret|token|key|credential|api_key|apikey)(?:[^a-zA-Z]|$)',
    re.IGNORECASE,
)

# Replacement marker for scrubbed values
_PII_REPLACEMENT = "[REDACTED]"


@dataclass
class LLMConfig:
    """Configuration for LLM auto-instrumentation."""

    enabled: bool = True
    """Master toggle for all LLM instrumentation."""

    openai: bool = True
    """Enable OpenAI instrumentation."""

    anthropic: bool = True
    """Enable Anthropic instrumentation."""

    capture_content: bool = False
    """Capture prompt/completion content (off by default for privacy)."""


def resolve_capture_content(config: LLMConfig) -> bool:
    """
    Resolve whether content capture is enabled.

    Checks TRACEKIT_LLM_CAPTURE_CONTENT env var first, falls back to config.

    Args:
        config: LLM configuration

    Returns:
        True if content capture is enabled
    """
    env_val = os.environ.get("TRACEKIT_LLM_CAPTURE_CONTENT", "").lower()
    if env_val in ("true", "1", "yes"):
        return True
    if env_val in ("false", "0", "no"):
        return False
    return config.capture_content


def set_gen_ai_request_attributes(
    span: Span,
    model: str,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
) -> None:
    """
    Set GenAI request attributes on a span.

    Args:
        span: The span to set attributes on
        model: The requested model name
        max_tokens: Maximum tokens requested
        temperature: Temperature parameter
        top_p: Top-p parameter
    """
    span.set_attribute("gen_ai.operation.name", "chat")
    span.set_attribute("gen_ai.request.model", model)

    if max_tokens is not None:
        span.set_attribute("gen_ai.request.max_tokens", max_tokens)
    if temperature is not None:
        span.set_attribute("gen_ai.request.temperature", temperature)
    if top_p is not None:
        span.set_attribute("gen_ai.request.top_p", top_p)


def set_gen_ai_response_attributes(
    span: Span,
    model: Optional[str] = None,
    response_id: Optional[str] = None,
    finish_reasons: Optional[List[str]] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
) -> None:
    """
    Set GenAI response attributes on a span.

    Args:
        span: The span to set attributes on
        model: The actual model that responded
        response_id: Provider response ID
        finish_reasons: List of finish reasons
        input_tokens: Prompt/input token count
        output_tokens: Completion/output token count
    """
    if model is not None:
        span.set_attribute("gen_ai.response.model", model)
    if response_id is not None:
        span.set_attribute("gen_ai.response.id", response_id)
    if finish_reasons is not None:
        span.set_attribute("gen_ai.response.finish_reasons", finish_reasons)
    if input_tokens is not None:
        span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
    if output_tokens is not None:
        span.set_attribute("gen_ai.usage.output_tokens", output_tokens)


def set_gen_ai_error_attributes(span: Span, error: Exception) -> None:
    """
    Set error attributes on a GenAI span.

    Args:
        span: The span to set error on
        error: The exception that occurred
    """
    span.set_attribute("error.type", type(error).__name__)
    span.record_exception(error)
    span.set_status(Status(StatusCode.ERROR, str(error)))


def record_tool_call_event(
    span: Span,
    name: str,
    call_id: Optional[str] = None,
    arguments: Optional[str] = None,
) -> None:
    """
    Record a tool call as a span event.

    Args:
        span: The span to add the event to
        name: Tool/function name
        call_id: Tool call ID
        arguments: JSON-serialized tool arguments
    """
    attrs: Dict[str, Any] = {"gen_ai.tool.name": name}
    if call_id is not None:
        attrs["gen_ai.tool.call.id"] = call_id
    if arguments is not None:
        attrs["gen_ai.tool.call.arguments"] = arguments
    span.add_event("gen_ai.tool.call", attributes=attrs)


def _scrub_pii(text: str) -> str:
    """
    Scrub potential PII values from text content.

    Looks for key-value patterns where the key matches sensitive names
    and replaces the associated value with [REDACTED].

    Args:
        text: Text to scrub

    Returns:
        Scrubbed text
    """
    if not text:
        return text

    # Scrub JSON-like key-value pairs: "password": "secret123" -> "password": "[REDACTED]"
    def _redact_json_values(match: re.Match) -> str:
        prefix = match.group(0)
        # Find the value after the key
        return prefix

    # Pattern to match "key": "value" or "key":"value" in JSON-like content
    scrubbed = re.sub(
        r'(["\'](?:password|passwd|pwd|secret|token|key|credential|api_key|apikey)["\'])\s*:\s*(["\'])(.+?)\2',
        lambda m: f'{m.group(1)}: {m.group(2)}{_PII_REPLACEMENT}{m.group(2)}',
        text,
        flags=re.IGNORECASE,
    )

    return scrubbed


def capture_input_messages(span: Span, messages: Any) -> None:
    """
    Capture input messages on a span (when content capture is enabled).

    Serializes messages to JSON and applies PII scrubbing.

    Args:
        span: The span to set attribute on
        messages: Input messages (list of dicts or similar)
    """
    try:
        content = json.dumps(messages, default=str)
        content = _scrub_pii(content)
        span.set_attribute("gen_ai.input.messages", content)
    except Exception:
        pass  # Never break user code for content capture


def capture_output_messages(span: Span, content: Any) -> None:
    """
    Capture output messages on a span (when content capture is enabled).

    Serializes output content to JSON and applies PII scrubbing.

    Args:
        span: The span to set attribute on
        content: Output content (string, dict, or list)
    """
    try:
        if isinstance(content, str):
            serialized = content
        else:
            serialized = json.dumps(content, default=str)
        serialized = _scrub_pii(serialized)
        span.set_attribute("gen_ai.output.messages", serialized)
    except Exception:
        pass  # Never break user code for content capture


def capture_system_instructions(span: Span, system: Any) -> None:
    """
    Capture system instructions on a span (when content capture is enabled).

    Args:
        span: The span to set attribute on
        system: System prompt/instructions (string or list)
    """
    try:
        if isinstance(system, str):
            serialized = system
        else:
            serialized = json.dumps(system, default=str)
        serialized = _scrub_pii(serialized)
        span.set_attribute("gen_ai.system_instructions", serialized)
    except Exception:
        pass  # Never break user code for content capture
