"""Shared API error format: {"error": {"code": ..., "message": ...}}."""

import logging
from datetime import date
from decimal import Decimal
from typing import Any, Protocol

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class ErrorCode:
    UNAUTHENTICATED = "unauthenticated"
    VALIDATION_ERROR = "validation_error"
    NOT_FOUND = "not_found"
    SERVICE_UNAVAILABLE = "service_unavailable"
    INTERNAL_ERROR = "internal_error"
    PROVIDER_KEY_MISSING = "provider_key_missing"
    PROVIDER_KEY_INVALID = "provider_key_invalid"
    PROVIDER_KEY_REJECTED = "provider_key_rejected"
    PROVIDER_UNREACHABLE = "provider_unreachable"
    PROVIDER_RATE_LIMITED = "provider_rate_limited"
    PROVIDER_REQUEST_REFUSED = "provider_request_refused"
    MODEL_NOT_SET = "model_not_set"
    MODEL_UNKNOWN = "model_unknown"
    MODEL_UNSUPPORTED = "model_unsupported"
    MODEL_UNAVAILABLE = "model_unavailable"
    CONTEXT_FULL = "context_full"
    CONVERSATION_BUSY = "conversation_busy"
    # The month's usage reached the user's spend cap: a refused message, or
    # the `error` event of a turn that crossed it between rounds.
    SPEND_CAP_REACHED = "spend_cap_reached"
    # Only ever sent as an `error` event inside a chat stream.
    OUTPUT_LIMIT_REACHED = "output_limit_reached"
    TOOL_LOOP_LIMIT = "tool_loop_limit"
    # Also stored on an answer the server stopped (shutdown or restart).
    ANSWER_INTERRUPTED = "answer_interrupted"
    # The user pressed Stop: stored on the stopped answer too.
    ANSWER_STOPPED = "answer_stopped"
    NOT_ALLOWED = "not_allowed"
    DEMO_SESSION_EXPIRED = "demo_session_expired"
    DEMO_FULL = "demo_full"
    RATE_LIMITED = "rate_limited"
    EMBEDDING_MISMATCH = "embedding_mismatch"
    CATEGORY_EXISTS = "category_exists"
    PROPOSAL_PART_SAVED = "proposal_part_saved"
    THOUGHT_CHANGED = "thought_changed"
    # MCP connectors: a server that could not be used (app/mcp_client.py).
    CONNECTOR_UNREACHABLE = "connector_unreachable"
    CONNECTOR_AUTH_FAILED = "connector_auth_failed"
    CONNECTOR_PROTOCOL_ERROR = "connector_protocol_error"
    USER_CONNECTORS_DISABLED = "user_connectors_disabled"
    OPERATOR_CONNECTOR = "operator_connector"
    TOO_MANY_TOOLS = "too_many_tools"
    ACTION_EXPIRED = "action_expired"
    ACTION_RUNNING = "action_running"
    SETUP_TOKEN_INVALID = "setup_token_invalid"
    SETUP_INCOMPLETE = "setup_incomplete"


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        # Extra response headers, for example the conversation a refused chat
        # message was stored in.
        self.headers = headers or {}
        # Extra keys of the error object beside code and message, for example
        # the thought's current fields on thought_changed.
        self.extra = extra or {}


def model_not_set() -> ApiError:
    return ApiError(
        409, ErrorCode.MODEL_NOT_SET, "No chat model is set. Choose one in the model settings."
    )


def model_unknown(provider_label: str, model: str) -> ApiError:
    return ApiError(
        400,
        ErrorCode.MODEL_UNKNOWN,
        f"{provider_label} does not list the model '{model}' for your key.",
    )


def model_unsupported(model: str, what: str) -> ApiError:
    return ApiError(400, ErrorCode.MODEL_UNSUPPORTED, f"The model '{model}' does not support {what}.")


def embedding_mismatch(detail: str) -> ApiError:
    return ApiError(
        409,
        ErrorCode.EMBEDDING_MISMATCH,
        f"The search index was built with another embedding model ({detail}). "
        "Ask the operator to rebuild it.",
    )


def model_unavailable(model: str) -> ApiError:
    return ApiError(
        409,
        ErrorCode.MODEL_UNAVAILABLE,
        f"The model '{model}' is not available to your key. Choose another in the model settings.",
    )


def context_full(connectors: bool = False) -> ApiError:
    """connectors: some are on in the conversation, so turning them off is advised too."""
    advice = (
        "Use /compact, choose a model with a larger context, start a new conversation, "
        "or turn some connectors off."
        if connectors
        else "Use /compact, choose a model with a larger context, or start a new conversation."
    )
    return ApiError(
        409, ErrorCode.CONTEXT_FULL, f"This conversation is too long for the model. {advice}"
    )


def conversation_busy() -> ApiError:
    return ApiError(
        409,
        ErrorCode.CONVERSATION_BUSY,
        "This conversation is still answering another message. Wait for it to finish.",
    )


def conversation_delete_busy() -> ApiError:
    """A conversation's delete while its answer still runs after the stop
    (design decision 13)."""
    return ApiError(
        409,
        ErrorCode.CONVERSATION_BUSY,
        "An answer in this conversation is still running. Try deleting again in a moment.",
    )


def turns_busy() -> ApiError:
    """A delete of the user's content, account, or demo session while one of
    their answers still runs or is still being opened (design decision 13)."""
    return ApiError(
        409, ErrorCode.CONVERSATION_BUSY, "An answer is still running. Try again in a moment."
    )


class CapFigures(Protocol):
    """What the spend cap refusal names (`app.chat.usage.CapState`)."""

    unit: str
    amount: Decimal
    used: Decimal
    resets_on: date


_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)  # fmt: skip


def format_cap_amount(unit: str, amount: Decimal) -> str:
    """"$5.00" or "2,000,000 tokens", as the usage settings show a threshold:
    dollars with at least 2 and at most 6 decimals, tokens as a whole number."""
    if unit == "tokens":
        return f"{int(amount):,} token{'' if amount == 1 else 's'}"
    text = f"{amount.quantize(Decimal('0.000001')):,f}".rstrip("0")
    whole, _, cents = text.partition(".")
    return f"${whole}.{cents.ljust(2, '0')}"


def spend_cap_reached(state: CapFigures) -> ApiError:
    """The month's usage reached the cap (design decision 9). The message
    names the cap and the month so far in its unit, never dollars for a
    token cap, and the day it resets, in UTC."""
    so_far = format_cap_amount(state.unit, state.used)
    if state.unit == "usd":
        so_far += ", estimated"
    resets = state.resets_on
    return ApiError(
        409,
        ErrorCode.SPEND_CAP_REACHED,
        f"Your monthly spend cap of {format_cap_amount(state.unit, state.amount)} is reached "
        f"(this month so far: {so_far}). Raise or remove it in Settings to keep chatting. "
        f"It resets on {resets.day} {_MONTHS[resets.month - 1]} (UTC).",
    )


# The two stream-only errors never become a response, so their status is unused.
def output_limit_reached(thinking_only: bool) -> ApiError:
    message = (
        "The model ran out of room while thinking and wrote no answer. "
        "Try a lower reasoning effort or another model."
        if thinking_only
        else "The model ran out of room before finishing. Try again, or use a lower reasoning effort."
    )
    return ApiError(200, ErrorCode.OUTPUT_LIMIT_REACHED, message)


def tool_loop_limit() -> ApiError:
    return ApiError(
        200,
        ErrorCode.TOOL_LOOP_LIMIT,
        "The model kept using tools without finishing its answer. Try again.",
    )


def answer_interrupted() -> ApiError:
    return ApiError(
        200,
        ErrorCode.ANSWER_INTERRUPTED,
        "This answer did not finish. Send the message again to retry.",
    )


def answer_stopped() -> ApiError:
    return ApiError(200, ErrorCode.ANSWER_STOPPED, "You stopped this answer.")


def not_allowed() -> ApiError:
    return ApiError(
        403,
        ErrorCode.NOT_ALLOWED,
        "This instance does not accept your account. Ask its operator to add your "
        "verified email address.",
    )


def setup_token_invalid() -> ApiError:
    # One message for a missing, empty, wrong, or old token.
    return ApiError(
        403,
        ErrorCode.SETUP_TOKEN_INVALID,
        "The setup token is missing or not valid. Use the token the backend printed "
        "in its log at its last start.",
    )


def setup_incomplete(message: str) -> ApiError:
    return ApiError(409, ErrorCode.SETUP_INCOMPLETE, message)


def demo_session_expired() -> ApiError:
    return ApiError(
        401,
        ErrorCode.DEMO_SESSION_EXPIRED,
        "Your demo session has ended and its data was deleted. Start a new one.",
    )


def demo_full() -> ApiError:
    return ApiError(503, ErrorCode.DEMO_FULL, "The demo is full. Try again later.")


def rate_limited(retry_after_seconds: int) -> ApiError:
    seconds = max(1, retry_after_seconds)
    return ApiError(
        429,
        ErrorCode.RATE_LIMITED,
        f"Too many requests. Try again in {seconds} seconds.",
        headers={"Retry-After": str(seconds)},
    )


def user_connectors_disabled() -> ApiError:
    return ApiError(
        403,
        ErrorCode.USER_CONNECTORS_DISABLED,
        "This server does not let users add their own connectors.",
    )


def operator_connector() -> ApiError:
    return ApiError(
        403,
        ErrorCode.OPERATOR_CONNECTOR,
        "This connector is set up by the server's operator and can't be changed or removed.",
    )


# The three connector failure codes (app/mcp_client.py ConnectorError). The
# reason reads after "the server": "could not be reached", "refused the auth".
CONNECTOR_FAILURE_CODES = (
    ErrorCode.CONNECTOR_UNREACHABLE,
    ErrorCode.CONNECTOR_AUTH_FAILED,
    ErrorCode.CONNECTOR_PROTOCOL_ERROR,
)


def connector_failed(code: str, reason: str) -> ApiError:
    if code not in CONNECTOR_FAILURE_CODES:
        raise ValueError(f"{code} is not a connector failure code")
    return ApiError(502, code, f"The server {reason}.")


def too_many_tools(limit: int) -> ApiError:
    return ApiError(
        422,
        ErrorCode.TOO_MANY_TOOLS,
        f"A conversation can have at most {limit} connector tools switched on. Turn a "
        "connector off here, or switch some of its tools off in settings.",
    )


def action_expired() -> ApiError:
    return ApiError(
        409,
        ErrorCode.ACTION_EXPIRED,
        "This action expired: the conversation moved on, or its tool is no longer on. "
        "Ask again in the chat if you still want it.",
    )


def action_running() -> ApiError:
    return ApiError(
        409, ErrorCode.ACTION_RUNNING, "This action is already running. Wait for its outcome."
    )


_HTTP_STATUS_CODES = {
    401: ErrorCode.UNAUTHENTICATED,
    404: ErrorCode.NOT_FOUND,
    422: ErrorCode.VALIDATION_ERROR,
    503: ErrorCode.SERVICE_UNAVAILABLE,
}


def error_response(
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {**(extra or {}), "code": code, "message": message}},
        headers=headers,
    )


async def _handle_api_error(_request: Request, exc: ApiError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message, exc.headers, exc.extra)


async def _handle_validation_error(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
    detail = first.get("msg", "Invalid request")
    message = f"{field}: {detail}" if field else detail
    return error_response(422, ErrorCode.VALIDATION_ERROR, message)


async def _handle_http_error(
    _request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    code = _HTTP_STATUS_CODES.get(exc.status_code, "http_error")
    return error_response(exc.status_code, code, str(exc.detail))


async def _handle_unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error", exc_info=exc)
    return error_response(500, ErrorCode.INTERNAL_ERROR, "Something went wrong.")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _handle_api_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)
