"""Thin, one-shot Agno runner for Knowledge generation.

Maya owns request freezing, authorization, Provider accounting, transport and
accepted staging. This module only fences Agno's public execution path and
hands the final SDK messages to that caller exactly once.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from threading import Lock
from typing import Any

from agno.agent import Agent
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.run.base import RunStatus


class KnowledgeGenerationInvokeError(RuntimeError):
    """Safe failure from the bounded Agno invocation path."""

    def __init__(self, safe_error_code: str) -> None:
        self.safe_error_code = safe_error_code
        super().__init__(safe_error_code)


DispatchOnce = Callable[[Sequence[Message]], ModelResponse]


class _KnowledgeGenerationModel(Model):
    """Public Agno Model adapter that permits one text-only dispatch."""

    def __init__(self, model_key: str, dispatch_once: DispatchOnce) -> None:
        super().__init__(
            id=model_key,
            name="Maya Knowledge generation",
            provider="maya",
            retries=0,
            retry_with_guidance=False,
            retry_with_guidance_limit=0,
            cache_response=False,
        )
        self._dispatch_once = dispatch_once
        self._invoked = False
        self._invoke_lock = Lock()

    @staticmethod
    def _validate_messages(messages: object) -> tuple[Message, ...]:
        if not isinstance(messages, (list, tuple)) or len(messages) != 2:
            raise KnowledgeGenerationInvokeError("knowledge_generation_messages_invalid")

        captured: list[Message] = []
        for expected_role, value in zip(("system", "user"), messages, strict=True):
            if (
                not isinstance(value, Message)
                or value.role != expected_role
                or not isinstance(value.content, str)
                or value.name is not None
                or value.tool_calls
                or value.audio
                or value.images
                or value.videos
                or value.files
                or value.audio_output is not None
                or value.image_output is not None
                or value.video_output is not None
                or value.file_output is not None
            ):
                raise KnowledgeGenerationInvokeError("knowledge_generation_messages_invalid")
            captured.append(value)
        return tuple(captured)

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        del args
        with self._invoke_lock:
            if self._invoked:
                raise KnowledgeGenerationInvokeError("knowledge_invocation_already_bound")
            self._invoked = True

        messages = self._validate_messages(kwargs.get("messages"))
        if kwargs.get("tools") or kwargs.get("tool_choice") is not None:
            raise KnowledgeGenerationInvokeError("knowledge_generation_tools_unsupported")
        if kwargs.get("stream") is True or kwargs.get("stream_events") is True:
            raise KnowledgeGenerationInvokeError("knowledge_generation_stream_unsupported")

        try:
            response = self._dispatch_once(messages)
        except KnowledgeGenerationInvokeError:
            raise
        except Exception:
            # Callback exceptions can contain request bodies, credentials or
            # transport diagnostics. The durable Maya operation owns the safe
            # error; never echo the original exception through Agent.RunOutput.
            raise KnowledgeGenerationInvokeError("knowledge_generation_dispatch_failed") from None

        if (
            not isinstance(response, ModelResponse)
            or response.role not in (None, "assistant")
            or not isinstance(response.content, str)
            or not response.content
            or response.tool_calls
            or response.audio is not None
            or response.images
            or response.videos
            or response.audios
            or response.files
            or response.reasoning_content
            or response.redacted_reasoning_content
            or response.parsed is not None
            or response.provider_data
            or response.citations
            or response.extra
        ):
            raise KnowledgeGenerationInvokeError("knowledge_generation_response_invalid")
        return response

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise KnowledgeGenerationInvokeError("knowledge_generation_stream_unsupported")

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        del args, kwargs
        if False:
            yield ModelResponse()
        raise KnowledgeGenerationInvokeError("knowledge_generation_stream_unsupported")

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        del response, kwargs
        raise KnowledgeGenerationInvokeError("knowledge_generation_response_invalid")

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        del response
        raise KnowledgeGenerationInvokeError("knowledge_generation_stream_unsupported")


def run_knowledge_generation_agent(
    *,
    system_message: str,
    user_message: str,
    model_key: str,
    dispatch_once: DispatchOnce,
) -> RunOutput:
    """Run one fresh Agent and fail unless Agno completes with plain text.

    ``dispatch_once`` receives the actual messages Agno built, in order. It is
    the only supported point where the caller may freeze bytes and dispatch.
    """

    if (
        not isinstance(system_message, str)
        or not system_message
        or not isinstance(user_message, str)
        or not user_message
        or not isinstance(model_key, str)
        or not model_key
    ):
        raise KnowledgeGenerationInvokeError("knowledge_generation_input_invalid")

    model = _KnowledgeGenerationModel(model_key, dispatch_once)
    agent = Agent(
        name="Maya Knowledge generation",
        model=model,
        system_message=system_message,
        build_context=False,
        build_user_context=False,
        tools=None,
        output_schema=None,
        parser_model=None,
        output_model=None,
        parse_response=False,
        structured_outputs=False,
        use_json_mode=False,
        fallback_config=None,
        fallback_models=None,
        tool_call_limit=None,
        retries=0,
        telemetry=False,
        cache_callables=False,
        cache_session=False,
        db=None,
        add_history_to_context=False,
        read_chat_history=False,
        read_tool_call_history=False,
        search_past_sessions=False,
        enable_agentic_memory=False,
        update_memory_on_run=False,
        add_memories_to_context=False,
        enable_session_summaries=False,
        add_session_summary_to_context=False,
        add_session_state_to_context=False,
        add_dependencies_to_context=False,
        add_knowledge_to_context=False,
        add_search_knowledge_instructions=False,
        add_learnings_to_context=False,
        search_knowledge=False,
        update_knowledge=False,
        send_media_to_model=False,
        add_name_to_context=False,
        add_datetime_to_context=False,
        add_location_to_context=False,
        store_history_messages=False,
        store_media=False,
        store_tool_messages=False,
        store_events=False,
        stream=False,
        stream_events=False,
        followups=False,
        markdown=False,
    )

    try:
        output = agent.run(
            Message(role="user", content=user_message),
            stream=False,
            stream_events=False,
        )
    except KnowledgeGenerationInvokeError:
        raise
    except Exception:
        raise KnowledgeGenerationInvokeError("knowledge_generation_run_failed") from None

    if (
        not isinstance(output, RunOutput)
        or output.status != RunStatus.completed
        or not isinstance(output.content, str)
        or not output.content
        or output.tools
        or output.audio
        or output.videos
        or output.files
    ):
        raise KnowledgeGenerationInvokeError("knowledge_generation_run_failed")
    return output
