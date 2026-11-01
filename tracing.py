import logging
from contextvars import ContextVar

# One id per graph run. main.py also passes it as the LangSmith run_id,
# so a trace id in app.log can be pasted straight into LangSmith's search.
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")


class TraceIdFilter(logging.Filter):
    """Stamps every log record with the current run's trace id."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = trace_id_var.get()
        return True


def setup_logging():
    handlers = [
        logging.FileHandler("app.log"),
        logging.StreamHandler(),
    ]
    for handler in handlers:
        handler.addFilter(TraceIdFilter())

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] [trace=%(trace_id)s] %(name)s: %(message)s",
        handlers=handlers,
    )

    # Every OpenAI call is already in LangSmith; keep app.log to the blocks below
    logging.getLogger("httpx").setLevel(logging.WARNING)


def log_block(logger: logging.Logger, title: str, *lines: str):
    """Logs one readable section, e.g. ========== NODE ========== followed by its lines."""
    logger.info("\n========== %s ==========\n%s\n", title, "\n".join(lines))


def preview(text: str, limit: int = 200) -> str:
    """First part of a long LLM answer; the full text is in the LangSmith trace."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + "..."


def log_llm_response(logger: logging.Logger, response):
    """Logs why the LLM stopped and either the tools it asked for or a preview of its answer."""
    lines = [f"Finish reason: {response.response_metadata.get('finish_reason')}"]

    for tool_call in response.tool_calls:
        lines.append(f"→ TOOL REQUEST: {tool_call['name']}")
        lines.append("→ ARGS:")
        lines.extend(f"   {name}: {value}" for name, value in tool_call["args"].items())

    if not response.tool_calls:
        lines.append("")
        lines.append("→ FINAL RESPONSE:")
        lines.append(preview(response.content))

    log_block(logger, "LLM", *lines)
