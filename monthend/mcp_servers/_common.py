"""Shared plumbing for the MCP servers."""

from __future__ import annotations

import functools
import json
import logging
import os
import sys
from decimal import Decimal

from monthend.review import GateError
from monthend.sources.http import IntegrationError

# MCP servers are agent infrastructure: anything they call is, by definition, not a person.
os.environ.setdefault("MONTHEND_AGENT_SESSION", "mcp")
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def plain(data):
    """Make results JSON-safe (Decimals become strings so no precision is lost)."""
    return json.loads(json.dumps(data, default=lambda o: str(o) if isinstance(o, Decimal) else repr(o)))


def tool_errors(fn):
    """Return refusals and integration failures as data the agent can read and act on, not as crashes."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return plain(fn(*args, **kwargs))
        except GateError as exc:
            return {"error": "refused_by_review_gate", "message": str(exc)}
        except IntegrationError as exc:
            return {"error": "integration_error", "message": str(exc)}
        except (KeyError, ValueError, FileNotFoundError) as exc:
            return {"error": "bad_request", "message": str(exc)}

    return wrapper
