"""Shared API error format: {"error": {"code": ..., "message": ...}}."""

import logging

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
    # Only ever sent as an `error` event inside a chat stream.
    OUTPUT_LIMIT_REACHED = "output_limit_reached"
    TOOL_LOOP_LIMIT = "tool_loop_limit"
    NOT_ALLOWED = "not_allowed"
    DEMO_SESSION_EXPIRED = "demo_session_expired"
    DEMO_FULL = "demo_full"
    RATE_LIMITED = "rate_limited"
    EMBEDDING_MISMATCH = "embedding_mismatch"
    CATEGORY_EXISTS = "category_exists"
    PROPOSAL_PART_SAVED = "proposal_part_saved"


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        # Extra response headers, for example the conversation a refused chat
        # message was stored in.
        self.headers = headers or {}


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


def context_full() -> ApiError:
    return ApiError(
        409,
        ErrorCode.CONTEXT_FULL,
        "This conversation is too long for the model. Use /compact, choose a model "
        "with a larger context, or start a new conversation.",
    )


def conversation_busy() -> ApiError:
    return ApiError(
        409,
        ErrorCode.CONVERSATION_BUSY,
        "This conversation is still answering another message. Wait for it to finish.",
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


def not_allowed() -> ApiError:
    return ApiError(
        403,
        ErrorCode.NOT_ALLOWED,
        "This instance does not accept your account. Ask its operator to add your "
        "verified email address.",
    )


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


_HTTP_STATUS_CODES = {
    401: ErrorCode.UNAUTHENTICATED,
    404: ErrorCode.NOT_FOUND,
    422: ErrorCode.VALIDATION_ERROR,
    503: ErrorCode.SERVICE_UNAVAILABLE,
}


def error_response(
    status_code: int, code: str, message: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
        headers=headers,
    )


async def _handle_api_error(_request: Request, exc: ApiError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message, exc.headers)


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
