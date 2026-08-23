"""
The agentic chat turn.

``run_agent_request`` is the agent-mode twin of tasks.process_ai_request:
same thread, cache key, heartbeat and terminal payload, so the poller,
cancellation and message creation in views.ai_status are shared. What
differs is the middle: no context selector; a small orientation prompt
(agent_prompt), read-only tools (agent_tools) and a provider tool loop
(anthropic_client / gemini_client) that reads what it needs. The final
answer then goes through the same finalize_response as the classic
turn, so fenced writes, handle links and the citation check stay one
path. The completion payload adds ``agent_run`` (agent_state) for the
message's trail.

Runs are minutes long and, like every chat turn, live on a daemon thread
in the web worker: a deploy or .py reload kills them (status.py's
heartbeat reports it).
"""

import logging
import time

from .agent_prompt import build_agent_history, build_agent_system
from .agent_state import AgentRunState, AgentStatusWriter
from .agent_tools import DEFAULT_BUDGET, build_agent_tools, make_agent_executor
from .agent_types import AgentProviderError
from .anthropic_client import send_to_claude_with_tools
from .gemini_client import send_to_gemini_with_tools
from .status import RunHeartbeat

logger = logging.getLogger(__name__)

# Share of the model window the orientation plus history may fill; the
# rest is headroom for the tool results appended during the turn.
AGENT_HISTORY_CEILING = 0.45
AGENT_CLAUDE_EFFORT = "high"
AGENT_MAX_OUTPUT_TOKENS = 16_000

REFUSAL_MESSAGE = (
    "The model declined this request (safety refusal). Try rephrasing, or "
    "a different model."
)


def run_agent_request(
    conversation_id: int,
    matter_id: int,
    user_message: str,
    user_id: int,
    llm: str,
):
    from django.contrib.auth import get_user_model

    from apps.matters.models import Matter

    from .models import Conversation
    from .tasks import (
        CLAUDE_FALLBACK_MODEL,
        CLAUDE_MODELS,
        GEMINI_MODELS,
        PromptTooLargeError,
        finalize_response,
        fit_prompt_to_window,
    )

    cache_key = f"ai_status_{conversation_id}"
    started_at = time.time()
    budget = DEFAULT_BUDGET
    if llm in GEMINI_MODELS:
        model = GEMINI_MODELS[llm]
    else:
        model = CLAUDE_MODELS.get(llm, CLAUDE_FALLBACK_MODEL)

    state = AgentRunState(conversation_id, llm, model, budget, started_at)
    writer = AgentStatusWriter(cache_key, state)
    result = None

    def error_payload(message: str) -> dict:
        return {
            "status": "error",
            "message": message,
            "activity_log": state.activity_log,
            "agent_run": state.to_persisted(result, time.time() - started_at),
        }

    heartbeat = RunHeartbeat(conversation_id).start()
    try:
        writer.set("context", "Orienting on the case file...")

        User = get_user_model()
        matter = Matter.objects.get(id=matter_id)
        user = User.objects.get(id=user_id)
        conversation = Conversation.objects.get(id=conversation_id)
        draft_link = getattr(conversation, "draft_link", None)

        system = build_agent_system(
            matter, user, conversation, user_message, budget=budget, log=writer.log
        )
        if writer.is_cancelled():
            return

        history = build_agent_history(conversation)
        history, prompt_tokens = fit_prompt_to_window(
            "\n\n".join(system),
            history,
            llm,
            writer.log,
            ceiling_share=AGENT_HISTORY_CEILING,
        )
        writer.log(
            f"History: {len(history)} messages; orientation ~{prompt_tokens:,} tokens"
        )

        tools = build_agent_tools(budget)
        execute_batch = make_agent_executor(
            matter,
            conversation,
            budget,
            on_event=writer.tool_event,
            is_cancelled=writer.is_cancelled,
        )
        state.tool_usage = execute_batch.usage

        writer.set("connecting", "Connecting to AI...")
        if writer.is_cancelled():
            return
        writer.log(f"Request submitted to {model}")
        writer.set("thinking", "Thinking...")

        common = dict(
            max_turns=budget.max_turns,
            is_cancelled=writer.is_cancelled,
            on_text=writer.narrative,
            on_thinking=writer.thinking,
            on_turn=writer.turn,
            on_note=writer.note,
            max_tokens=AGENT_MAX_OUTPUT_TOKENS,
        )
        if llm in GEMINI_MODELS:
            result = send_to_gemini_with_tools(
                system, history, tools, execute_batch, model, **common
            )
        else:
            result = send_to_claude_with_tools(
                system,
                history,
                tools,
                execute_batch,
                model,
                effort=AGENT_CLAUDE_EFFORT,
                **common,
            )

        if writer.is_cancelled():
            return

        response_text = result.text
        if result.stop_reason == "refusal" and not response_text.strip():
            response_text = REFUSAL_MESSAGE
        elif result.stop_reason == "max_tokens":
            writer.log("The answer hit the output limit and may be cut short")

        tool_usage = execute_batch.usage()
        writer.log(
            f"Answer received: {result.turns} model turn"
            f"{'s' if result.turns != 1 else ''}, "
            f"{tool_usage['tool_calls']} tool call"
            f"{'s' if tool_usage['tool_calls'] != 1 else ''}, "
            f"{int(time.time() - started_at)}s"
        )

        response_text, citations_data = finalize_response(
            response_text,
            matter,
            user,
            conversation,
            draft_link,
            writer.set,
            writer.log,
        )

        if writer.is_cancelled():
            return

        writer.complete(
            {
                "status": "complete",
                "message": "Complete",
                "response": response_text,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "citations": citations_data,
                "activity_log": state.activity_log,
                "agent_run": state.to_persisted(result, time.time() - started_at),
            }
        )

    except InterruptedError:
        logger.info("Agent request cancelled for conversation %s", conversation_id)

    except PromptTooLargeError as exc:
        logger.warning("Agent prompt too large for conversation %s", conversation_id)
        writer.complete(error_payload(str(exc)))

    except AgentProviderError as exc:
        logger.warning(
            "Agent provider stopped conversation %s: %s", conversation_id, exc
        )
        writer.complete(error_payload(f"The model stopped the turn: {exc}"))

    except Exception as exc:
        logger.exception("Error in agent request for conversation %s", conversation_id)
        writer.complete(error_payload(f"Error: {exc}"))

    finally:
        heartbeat.stop()
