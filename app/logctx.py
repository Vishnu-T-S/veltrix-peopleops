"""The id of the request being handled, so every log line of one request can be tied together."""
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# time.monotonic() value after which no new model call may start; set once per request by the API layer
deadline_var: ContextVar[float] = ContextVar("deadline", default=0.0)
