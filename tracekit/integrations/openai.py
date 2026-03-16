"""
TraceKit OpenAI Integration

Auto-instruments OpenAI chat completion calls with GenAI semantic convention spans.
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
    record_tool_call_event,
    resolve_capture_content,
    set_gen_ai_error_attributes,
    set_gen_ai_request_attributes,
    set_gen_ai_response_attributes,
)


_instrumented = False


def instrument_openai(tracer: trace.Tracer, config: LLMConfig) -> bool:
    """
    Instrument OpenAI chat completions with tracing.

    Monkey-patches openai.resources.chat.completions.Completions.create
    and AsyncCompletions.create to create spans for each call.

    Args:
        tracer: OpenTelemetry tracer instance
        config: LLM configuration

    Returns:
        True if instrumentation was applied, False if openai not available
    """
    global _instrumented
    if _instrumented:
        return True

    try:
        import openai
        import openai.resources.chat.completions as completions_mod
    except ImportError:
        return False

    should_capture = resolve_capture_content(config)

    # Patch sync Completions.create
    _original_create = completions_mod.Completions.create

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
            span.set_attribute("gen_ai.provider.name", "openai")

            # Capture input content if enabled
            if should_capture:
                messages = kwargs.get("messages")
                if messages:
                    capture_input_messages(span, messages)

            # For streaming, inject stream_options to get usage data
            if stream and "stream_options" not in kwargs:
                kwargs["stream_options"] = {"include_usage": True}
            elif stream and isinstance(kwargs.get("stream_options"), dict):
                if "include_usage" not in kwargs["stream_options"]:
                    kwargs["stream_options"]["include_usage"] = True

            result = _original_create(self, *args, **kwargs)

            if stream:
                return _OpenAIStreamWrapper(result, span, should_capture)

            # Non-streaming: extract response attributes
            _set_response_from_completion(span, result, should_capture)
            span.end()
            return result

        except Exception as e:
            set_gen_ai_error_attributes(span, e)
            span.end()
            raise

    completions_mod.Completions.create = _patched_create

    # Patch async AsyncCompletions.create
    _original_async_create = completions_mod.AsyncCompletions.create

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
            span.set_attribute("gen_ai.provider.name", "openai")

            if should_capture:
                messages = kwargs.get("messages")
                if messages:
                    capture_input_messages(span, messages)

            # For streaming, inject stream_options to get usage data
            if stream and "stream_options" not in kwargs:
                kwargs["stream_options"] = {"include_usage": True}
            elif stream and isinstance(kwargs.get("stream_options"), dict):
                if "include_usage" not in kwargs["stream_options"]:
                    kwargs["stream_options"]["include_usage"] = True

            result = await _original_async_create(self, *args, **kwargs)

            if stream:
                return _AsyncOpenAIStreamWrapper(result, span, should_capture)

            _set_response_from_completion(span, result, should_capture)
            span.end()
            return result

        except Exception as e:
            set_gen_ai_error_attributes(span, e)
            span.end()
            raise

    completions_mod.AsyncCompletions.create = _patched_async_create

    _instrumented = True
    return True


def _set_response_from_completion(span: trace.Span, result: Any, capture: bool) -> None:
    """Extract and set response attributes from a non-streaming completion."""
    try:
        response_model = getattr(result, "model", None)
        response_id = getattr(result, "id", None)
        system_fingerprint = getattr(result, "system_fingerprint", None)

        finish_reasons = []
        choices = getattr(result, "choices", None) or []
        for choice in choices:
            reason = getattr(choice, "finish_reason", None)
            if reason:
                finish_reasons.append(reason)

            # Record tool calls as events
            message = getattr(choice, "message", None)
            if message:
                tool_calls = getattr(message, "tool_calls", None) or []
                for tc in tool_calls:
                    func = getattr(tc, "function", None)
                    if func:
                        record_tool_call_event(
                            span,
                            name=getattr(func, "name", ""),
                            call_id=getattr(tc, "id", None),
                            arguments=getattr(func, "arguments", None),
                        )

        usage = getattr(result, "usage", None)
        input_tokens = getattr(usage, "prompt_tokens", None) if usage else None
        output_tokens = getattr(usage, "completion_tokens", None) if usage else None

        set_gen_ai_response_attributes(
            span,
            model=response_model,
            response_id=response_id,
            finish_reasons=finish_reasons if finish_reasons else None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

        if system_fingerprint:
            span.set_attribute("openai.response.system_fingerprint", system_fingerprint)

        # Capture output content if enabled
        if capture and choices:
            output = []
            for choice in choices:
                msg = getattr(choice, "message", None)
                if msg:
                    content = getattr(msg, "content", None)
                    role = getattr(msg, "role", None)
                    output.append({"role": role, "content": content})
            capture_output_messages(span, output)

    except Exception:
        pass  # Never break user code


class _OpenAIStreamWrapper:
    """
    Wraps an OpenAI streaming response to accumulate token usage
    and end the span when the stream completes.

    Yields all chunks transparently to the user.
    """

    def __init__(self, stream: Any, span: trace.Span, capture: bool):
        self._stream = stream
        self._span = span
        self._capture = capture
        self._model = None
        self._finish_reasons = []
        self._input_tokens = None
        self._output_tokens = None
        self._system_fingerprint = None
        self._response_id = None
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
            for chunk in self._stream:
                self._process_chunk(chunk)
                yield chunk
            self._finalize()
        except Exception as e:
            set_gen_ai_error_attributes(self._span, e)
            self._span.end()
            raise

    def _process_chunk(self, chunk: Any) -> None:
        """Extract metadata from a streaming chunk."""
        try:
            if not self._model:
                self._model = getattr(chunk, "model", None)
            if not self._response_id:
                self._response_id = getattr(chunk, "id", None)
            if not self._system_fingerprint:
                self._system_fingerprint = getattr(chunk, "system_fingerprint", None)

            choices = getattr(chunk, "choices", None) or []
            for choice in choices:
                reason = getattr(choice, "finish_reason", None)
                if reason and reason not in self._finish_reasons:
                    self._finish_reasons.append(reason)

                # Accumulate content for capture
                if self._capture:
                    delta = getattr(choice, "delta", None)
                    if delta:
                        content = getattr(delta, "content", None)
                        if content:
                            self._accumulated_content.append(content)

            # Token usage comes in the final chunk (with stream_options.include_usage)
            usage = getattr(chunk, "usage", None)
            if usage:
                self._input_tokens = getattr(usage, "prompt_tokens", None)
                self._output_tokens = getattr(usage, "completion_tokens", None)
        except Exception:
            pass

    def _finalize(self) -> None:
        """Set final attributes and end span."""
        try:
            set_gen_ai_response_attributes(
                self._span,
                model=self._model,
                response_id=self._response_id,
                finish_reasons=self._finish_reasons if self._finish_reasons else None,
                input_tokens=self._input_tokens,
                output_tokens=self._output_tokens,
            )
            if self._system_fingerprint:
                self._span.set_attribute(
                    "openai.response.system_fingerprint", self._system_fingerprint
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

    # Support iteration protocol attributes that users might access
    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


class _AsyncOpenAIStreamWrapper:
    """
    Wraps an async OpenAI streaming response to accumulate token usage
    and end the span when the stream completes.

    Yields all chunks transparently to the user.
    """

    def __init__(self, stream: Any, span: trace.Span, capture: bool):
        self._stream = stream
        self._span = span
        self._capture = capture
        self._model = None
        self._finish_reasons = []
        self._input_tokens = None
        self._output_tokens = None
        self._system_fingerprint = None
        self._response_id = None
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
            async for chunk in self._stream:
                self._process_chunk(chunk)
                yield chunk
            self._finalize()
        except Exception as e:
            set_gen_ai_error_attributes(self._span, e)
            self._span.end()
            raise

    def _process_chunk(self, chunk: Any) -> None:
        """Extract metadata from a streaming chunk."""
        try:
            if not self._model:
                self._model = getattr(chunk, "model", None)
            if not self._response_id:
                self._response_id = getattr(chunk, "id", None)
            if not self._system_fingerprint:
                self._system_fingerprint = getattr(chunk, "system_fingerprint", None)

            choices = getattr(chunk, "choices", None) or []
            for choice in choices:
                reason = getattr(choice, "finish_reason", None)
                if reason and reason not in self._finish_reasons:
                    self._finish_reasons.append(reason)

                if self._capture:
                    delta = getattr(choice, "delta", None)
                    if delta:
                        content = getattr(delta, "content", None)
                        if content:
                            self._accumulated_content.append(content)

            usage = getattr(chunk, "usage", None)
            if usage:
                self._input_tokens = getattr(usage, "prompt_tokens", None)
                self._output_tokens = getattr(usage, "completion_tokens", None)
        except Exception:
            pass

    def _finalize(self) -> None:
        """Set final attributes and end span."""
        try:
            set_gen_ai_response_attributes(
                self._span,
                model=self._model,
                response_id=self._response_id,
                finish_reasons=self._finish_reasons if self._finish_reasons else None,
                input_tokens=self._input_tokens,
                output_tokens=self._output_tokens,
            )
            if self._system_fingerprint:
                self._span.set_attribute(
                    "openai.response.system_fingerprint", self._system_fingerprint
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
