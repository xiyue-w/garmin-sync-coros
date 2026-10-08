import json


def parse_json_response(response, operation):
    """Report failed HTTP/JSON responses without exposing credentials or tokens."""
    status = response.status
    content_type = response.headers.get("Content-Type", "unknown")
    body = response.data
    context = (
        f"{operation}: HTTP {status}, Content-Type {content_type}, "
        f"body length {len(body)} bytes"
    )
    if not 200 <= status < 300:
        raise RuntimeError(context)
    try:
        return json.loads(body)
    except (ValueError, UnicodeDecodeError) as err:
        raise RuntimeError(f"{context}; expected JSON but received an empty or invalid body") from err
