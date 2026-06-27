from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

def get_request_id() -> str:
    return request_id_var.get() or "-"