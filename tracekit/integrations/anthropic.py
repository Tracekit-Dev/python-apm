"""
TraceKit Anthropic Integration

Auto-instruments Anthropic message creation calls with GenAI semantic convention spans.
Supports both sync and async methods, streaming and non-streaming.
"""

import json
from typing import Any, Optional

from opentelemetry import trace
from opentelemetry.trace import SpanKind

from tracekit.integrations.llm_common import (
    LLMConfig,
    capture_input_messages,
    capture_output_messages,
    capture_system_instructions,
    record_tool_call_event,
    resolve_capture_content,
    set_gen_ai_error_attributes,
    set_gen_ai_request_attributes,
    set_gen_ai_response_attributes,
)


_instrumented = False


def instrument_anthropic(tracer: trace.Tracer, config: LLMConfig) -> bool:
    """
    Instrument Anthropic message creation with tracing.

    Monkey-patches anthropic.resources.messages.Messages.create
    and AsyncMessages.create to create spans for each call.

    Args:
        tracer: OpenTelemetry tracer instance
        config: LLM configuration

    Returns:
        True if instrumentation was applied, False if anthropic not available
    """
    global _instrumented
    if _instrumented:
        return True

    try:
        import anthropic
        import anthropic.resources.messages as messages_mod
    except ImportError:
        return False

    should_capture = resolve_capture_content(config)

    # Patch sync Messages.create
    _original_create = messages_mod.Messages.create

    def _patched_create(self, *args, **kwargs):
        model = kwargs.get("model", "unknown")
        stream = kwargs.get("stream", False)

        span = tracer.start_span(
            f"chat {model}",
            kind=SpanKind.CLIENT,
        )

        try:
            # Set request attributes
            set_gen_ai_request_attributes(
                span,
                model=model,
                max_tokens=kwargs.get("max_tokens"),
                temperature=kwargs.get("temperature"),
                top_p=kwargs.get("top_p"),
            )
            span.set_attribute("gen_ai.provider.name", "anthropic")

            # Capture input content if enabled
            if should_capture:
                messages = kwargs.get("messages")
                if messages:
                    capture_input_messages(span, messages)
                system = kwargs.get("system")
                if system:
                    capture_system_instructions(span, system)

            result = _original_create(self, *args, **kwargs)

            if stream:
                return _AnthropicStreamWrapper(result, span, should_capture)

            # Non-streaming: extract response attributes
            _set_response_from_message(span, result, should_capture)
            span.end()
            return result

        except Exception as e:
            set_gen_ai_error_attributes(span, e)
            span.end()
            raise

    messages_mod.Messages.create = _patched_create

    # Patch async AsyncMessages.create
    _original_async_create = messages_mod.AsyncMessages.create

    async def _patched_async_create(self, *args, **kwargs):
        model = kwargs.get("model", "unknown")
        stream = kwargs.get("stream", False)

        span = tracer.start_span(
            f"chat {model}",
            kind=SpanKind.CLIENT,
        )

        try:
            set_gen_ai_request_attributes(
                span,
                model=model,
                max_tokens=kwargs.get("max_tokens"),
                temperature=kwargs.get("temperature"),
                top_p=kwargs.get("top_p"),
            )
            span.set_attribute("gen_ai.provider.name", "anthropic")

            if should_capture:
                messages = kwargs.get("messages")
                if messages:
                    capture_input_messages(span, messages)
                system = kwargs.get("system")
                if system:
                    capture_system_instructions(span, system)

            result = await _original_async_create(self, *args, **kwargs)

            if stream:
                return _AsyncAnthropicStreamWrapper(result, span, should_capture)

            _set_response_from_message(span, result, should_capture)
            span.end()
            return result

        except Exception as e:
            set_gen_ai_error_attributes(span, e)
            span.end()
            raise

    messages_mod.AsyncMessages.create = _patched_async_create

    _instrumented = True
    return True


def _set_response_from_message(span: trace.Span, result: Any, capture: bool) -> None:
    """Extract and set response attributes from a non-streaming Anthropic message."""
    try:
        response_model = getattr(result, "model", None)
        response_id = getattr(result, "id", None)
        stop_reason = getattr(result, "stop_reason", None)

        finish_reasons = [stop_reason] if stop_reason else None

        usage = getattr(result, "usage", None)
        input_tokens = getattr(usage, "input_tokens", None) if usage else None
        output_tokens = getattr(usage, "output_tokens", None) if usage else None

        set_gen_ai_response_attributes(
            span,
            model=response_model,
            response_id=response_id,
            finish_reasons=finish_reasons,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

        # Anthropic cache-specific token attributes
        if usage:
            cache_creation = getattr(usage, "cache_creation_input_tokens", None)
            cache_read = getattr(usage, "cache_read_input_tokens", None)
            if cache_creation is not None:
                span.set_attribute("gen_ai.usage.cache_creation.input_tokens", cache_creation)
            if cache_read is not None:
                span.set_attribute("gen_ai.usage.cache_read.input_tokens", cache_read)

        # Record tool calls as events
        content_blocks = getattr(result, "content", None) or []
        output_parts = []
        for block in content_blocks:
            block_type = getattr(block, "type", None)
            if block_type == "tool_use":
                name = getattr(block, "name", "")
                call_id = getattr(block, "id", None)
                arguments = getattr(block, "input", None)
                args_str = json.dumps(arguments) if arguments else None
                record_tool_call_event(span, name=name, call_id=call_id, arguments=args_str)
            if capture:
                if block_type == "text":
                    text = getattr(block, "text", "")
                    output_parts.append({"type": "text", "text": text})
                elif block_type == "tool_use":
                    output_parts.append({
                        "type": "tool_use",
                        "name": getattr(block, "name", ""),
                        "input": getattr(block, "input", {}),
                    })

        if capture and output_parts:
            capture_output_messages(span, output_parts)

    except Exception:
        pass  # Never break user code


class _AnthropicStreamWrapper:
    """
    Wraps an Anthropic streaming response to accumulate token usage
    and end the span when the stream completes.

    Anthropic streaming events:
    - message_start: contains usage.input_tokens
    - content_block_delta: contains text delta
    - message_delta: contains usage.output_tokens and stop_reason
    - message_stop: stream complete

    Yields all events transparently to the user.
    """

    def __init__(self, stream: Any, span: trace.Span, capture: bool):
        self._stream = stream
        self._span = span
        self._capture = capture
        self._model = None
        self._response_id = None
        self._stop_reason = None
        self._input_tokens = None
        self._output_tokens = None
        self._cache_creation_tokens = None
        self._cache_read_tokens = None
        self._accumulated_content = []

    def __iter__(self):
        return self._iterate()

    def __enter__(self):
        if hasattr(self._stream, "__enter__"):
            self._stream.__enter__()
        return self

    def __exit__(self, *args):
        if hasattr(self._stream, "__exit__"):
            self._stream.__exit__(*args)
        self._finalize()

    def _iterate(self):
        try:
            for event in self._stream:
                self._process_event(event)
                yield event
            self._finalize()
        except Exception as e:
            set_gen_ai_error_attributes(self._span, e)
            self._span.end()
            raise

    def _process_event(self, event: Any) -> None:
        """Extract metadata from a streaming event."""
        try:
            event_type = getattr(event, "type", None)

            if event_type == "message_start":
                message = getattr(event, "message", None)
                if message:
                    self._model = getattr(message, "model", None)
                    self._response_id = getattr(message, "id", None)
                    usage = getattr(message, "usage", None)
                    if usage:
                        self._input_tokens = getattr(usage, "input_tokens", None)
                        self._cache_creation_tokens = getattr(
                            usage, "cache_creation_input_tokens", None
                        )
                        self._cache_read_tokens = getattr(
                            usage, "cache_read_input_tokens", None
                        )

            elif event_type == "content_block_delta":
                if self._capture:
                    delta = getattr(event, "delta", None)
                    if delta:
                        delta_type = getattr(delta, "type", None)
                        if delta_type == "text_delta":
                            text = getattr(delta, "text", "")
                            if text:
                                self._accumulated_content.append(text)

            elif event_type == "message_delta":
                delta = getattr(event, "delta", None)
                if delta:
                    self._stop_reason = getattr(delta, "stop_reason", None)
                usage = getattr(event, "usage", None)
                if usage:
                    self._output_tokens = getattr(usage, "output_tokens", None)

        except Exception:
            pass

    def _finalize(self) -> None:
        """Set final attributes and end span."""
        try:
            finish_reasons = [self._stop_reason] if self._stop_reason else None

            set_gen_ai_response_attributes(
                self._span,
                model=self._model,
                response_id=self._response_id,
                finish_reasons=finish_reasons,
                input_tokens=self._input_tokens,
                output_tokens=self._output_tokens,
            )

            if self._cache_creation_tokens is not None:
                self._span.set_attribute(
                    "gen_ai.usage.cache_creation.input_tokens", self._cache_creation_tokens
                )
            if self._cache_read_tokens is not None:
                self._span.set_attribute(
                    "gen_ai.usage.cache_read.input_tokens", self._cache_read_tokens
                )

            if self._capture and self._accumulated_content:
                full_content = "".join(self._accumulated_content)
                capture_output_messages(
                    self._span,
                    [{"role": "assistant", "content": full_content}],
                )
        except Exception:
            pass
        self._span.end()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


class _AsyncAnthropicStreamWrapper:
    """
    Wraps an async Anthropic streaming response to accumulate token usage
    and end the span when the stream completes.

    Yields all events transparently to the user.
    """

    def __init__(self, stream: Any, span: trace.Span, capture: bool):
        self._stream = stream
        self._span = span
        self._capture = capture
        self._model = None
        self._response_id = None
        self._stop_reason = None
        self._input_tokens = None
        self._output_tokens = None
        self._cache_creation_tokens = None
        self._cache_read_tokens = None
        self._accumulated_content = []

    def __aiter__(self):
        return self._aiterate()

    async def __aenter__(self):
        if hasattr(self._stream, "__aenter__"):
            await self._stream.__aenter__()
        return self

    async def __aexit__(self, *args):
        if hasattr(self._stream, "__aexit__"):
            await self._stream.__aexit__(*args)
        self._finalize()

    async def _aiterate(self):
        try:
            async for event in self._stream:
                self._process_event(event)
                yield event
            self._finalize()
        except Exception as e:
            set_gen_ai_error_attributes(self._span, e)
            self._span.end()
            raise

    def _process_event(self, event: Any) -> None:
        """Extract metadata from a streaming event."""
        try:
            event_type = getattr(event, "type", None)

            if event_type == "message_start":
                message = getattr(event, "message", None)
                if message:
                    self._model = getattr(message, "model", None)
                    self._response_id = getattr(message, "id", None)
                    usage = getattr(message, "usage", None)
                    if usage:
                        self._input_tokens = getattr(usage, "input_tokens", None)
                        self._cache_creation_tokens = getattr(
                            usage, "cache_creation_input_tokens", None
                        )
                        self._cache_read_tokens = getattr(
                            usage, "cache_read_input_tokens", None
                        )

            elif event_type == "content_block_delta":
                if self._capture:
                    delta = getattr(event, "delta", None)
                    if delta:
                        delta_type = getattr(delta, "type", None)
                        if delta_type == "text_delta":
                            text = getattr(delta, "text", "")
                            if text:
                                self._accumulated_content.append(text)

            elif event_type == "message_delta":
                delta = getattr(event, "delta", None)
                if delta:
                    self._stop_reason = getattr(delta, "stop_reason", None)
                usage = getattr(event, "usage", None)
                if usage:
                    self._output_tokens = getattr(usage, "output_tokens", None)

        except Exception:
            pass

    def _finalize(self) -> None:
        """Set final attributes and end span."""
        try:
            finish_reasons = [self._stop_reason] if self._stop_reason else None

            set_gen_ai_response_attributes(
                self._span,
                model=self._model,
                response_id=self._response_id,
                finish_reasons=finish_reasons,
                input_tokens=self._input_tokens,
                output_tokens=self._output_tokens,
            )

            if self._cache_creation_tokens is not None:
                self._span.set_attribute(
                    "gen_ai.usage.cache_creation.input_tokens", self._cache_creation_tokens
                )
            if self._cache_read_tokens is not None:
                self._span.set_attribute(
                    "gen_ai.usage.cache_read.input_tokens", self._cache_read_tokens
                )

            if self._capture and self._accumulated_content:
                full_content = "".join(self._accumulated_content)
                capture_output_messages(
                    self._span,
                    [{"role": "assistant", "content": full_content}],
                )
        except Exception:
            pass
        self._span.end()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)
