"""Direct Claude API calls: commentary drafting, invoice extraction, and an LLM judge.

Claude Code subagents are the normal path for drafting (see .claude/agents/). This
module is the programmatic path used by the evaluation harness (to score many cases
without an interactive session) and by `monthend commentary draft --engine claude`.

House style comes from .claude/skills/variance-commentary/SKILL.md, so the agent
and the API path follow one written standard.

Every response is structured output checked twice: by schema (pydantic) and by the
deterministic validator. Validator failures are fed back for up to two repair turns.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from pathlib import Path

from monthend.config import ROOT
from monthend.evidence import EvidenceIndex
from monthend.extraction import ExtractedInvoice, Located, locate_amount
from monthend.money import dec
from monthend.pack import Pack
from monthend.snapshot import Document
from monthend.variance import Commentary, validate_commentary

log = logging.getLogger("monthend.llm")

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ModelError(RuntimeError):
    pass


def model_name() -> str:
    return os.environ.get("MONTHEND_MODEL", DEFAULT_MODEL)


def _client():
    import anthropic

    return anthropic.Anthropic(max_retries=4)


def skill_text(name: str) -> str:
    text = (ROOT / ".claude" / "skills" / name / "SKILL.md").read_text()
    return re.sub(r"\A---.*?---\s*", "", text, flags=re.S)


def _strict(obj: dict) -> dict:
    return {"type": "object", "additionalProperties": False, "required": list(obj), "properties": obj}


COMMENTARY_SCHEMA = _strict({
    "summary": {"type": "string"},
    "items": {"type": "array", "items": _strict({
        "line_key": {"type": "string"},
        "text": {"type": "string"},
        "drivers": {"type": "array", "items": _strict({
            "description": {"type": "string"},
            "amount": {"type": ["number", "null"]},
            "evidence": {"type": "array", "items": {"type": "string"}},
        })},
        "follow_up": {"type": "array", "items": {"type": "string"}},
    })},
})


def _create(messages: list[dict], system: str, schema: dict, *, model: str, effort: str = "high", max_tokens: int = 16000):
    """One structured-output request with server-side refusal fallback and explicit stop-reason handling."""
    import anthropic

    client = _client()
    try:
        with client.beta.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        ) as stream:
            response = stream.get_final_message()
    except anthropic.RateLimitError as exc:
        raise ModelError(f"Claude API rate limit persisted after retries: {exc.message}") from exc
    except anthropic.APIStatusError as exc:
        raise ModelError(f"Claude API error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise ModelError(f"could not reach the Claude API: {exc}") from exc
    if response.stop_reason == "refusal":
        raise ModelError(f"model declined the request ({getattr(response.stop_details, 'category', None)})")
    if response.stop_reason == "max_tokens":
        raise ModelError("response was cut off at max_tokens")
    text = next((b.text for b in response.content if b.type == "text"), "")
    log.info("claude %s usage in=%s out=%s request=%s", response.model, response.usage.input_tokens,
             response.usage.output_tokens, getattr(response, "_request_id", ""))
    return response, json.loads(text)


def draft_commentary_with_claude(pack: Pack, contexts: dict[str, dict], index: EvidenceIndex, *,
                                 model: str | None = None, repair_turns: int = 2) -> tuple[Commentary, list[dict]]:
    """Draft commentary, then repair it against the validator. Returns the draft and a trace of each attempt."""
    model = model or model_name()
    system = ("You draft management-pack variance commentary for an accounting firm. Follow this house standard exactly.\n\n"
              + skill_text("variance-commentary"))
    net = pack.line("pl.net_profit")
    request = {
        "client": pack.client_name, "period": pack.period_label, "currency": pack.currency,
        "net_profit": {k: (str(v) if v is not None else None) for k, v in net.values.items()},
        "material_lines": [l.key for l in pack.material_lines()],
        "variance_context": contexts,
    }
    messages = [{"role": "user", "content": "Draft the commentary for these material variances. Cite only evidence ids that "
                                           "appear in the context.\n\n" + json.dumps(request, indent=1)}]
    trace = []
    for attempt in range(repair_turns + 1):
        response, data = _create(messages, system, COMMENTARY_SCHEMA, model=model)
        commentary = Commentary(**data, author=f"claude:{response.model}")
        report = validate_commentary(commentary, pack, index)
        trace.append({"attempt": attempt, "ok": report.ok, "issues": [i.message for i in report.issues if i.severity != "info"]})
        if report.ok:
            return commentary, trace
        messages += [
            # Append the assistant turn unchanged (thinking blocks included): history must stay append-only.
            {"role": "assistant", "content": response.content},
            {"role": "user", "content": "The automated checks rejected this draft:\n- " + "\n- ".join(i.message for i in report.blocking)
                                        + "\nReturn a corrected full draft. Do not introduce figures that are not in the context."},
        ]
    return commentary, trace


# --------------------------------------------------------------------------- extraction

INVOICE_SCHEMA = _strict({
    "supplier": {"type": "string"},
    "invoice_number": {"type": "string"},
    "invoice_date": {"type": "string", "description": "DD/MM/YYYY as printed"},
    "subtotal": {"type": ["number", "null"]},
    "tax": {"type": ["number", "null"]},
    "total": {"type": ["number", "null"]},
})


def extract_invoice_with_claude(doc: Document, *, model: str | None = None) -> tuple[ExtractedInvoice, list[str]]:
    """Read an unfamiliar invoice layout. Every amount must be found in the PDF text or it is dropped."""
    data = base64.standard_b64encode(doc.path.read_bytes()).decode()
    messages = [{"role": "user", "content": [
        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}},
        {"type": "text", "text": "Extract the supplier invoice header fields. Copy numbers exactly as printed; use null if absent."},
    ]}]
    _, out = _create(messages, "You extract fields from supplier invoices for an accounting firm.", INVOICE_SCHEMA,
                     model=model or model_name(), effort="low", max_tokens=4000)
    problems: list[str] = []

    def ground(field: str, near: str) -> Located | None:
        if out.get(field) is None:
            return None
        located = locate_amount(doc, dec(out[field]), near=near) or locate_amount(doc, dec(out[field]))
        if located is None:
            problems.append(f"{field} {out[field]} was not found in the document text; discarded")
        return located

    invoice = ExtractedInvoice(
        supplier=out.get("supplier", ""),
        invoice_number=Located(dec(0), "", out.get("invoice_number", "")) if out.get("invoice_number") else None,
        invoice_date=Located(dec(0), "", out.get("invoice_date", "")) if out.get("invoice_date") else None,
        subtotal=ground("subtotal", "subtotal"), tax=ground("tax", "gst"), total=ground("total", "total"),
        method="claude",
    )
    if invoice.subtotal and invoice.tax and invoice.total and not invoice.arithmetic_ok():
        problems.append("subtotal + tax does not equal total")
    return invoice, problems


# --------------------------------------------------------------------------- judge

JUDGE_SCHEMA = _strict({
    "scores": {"type": "array", "items": _strict({
        "line_key": {"type": "string"},
        "plain_english": {"type": "integer", "description": "1-5: a business owner understands it without accounting training"},
        "explains_cause": {"type": "integer", "description": "1-5: names the real business cause shown in the evidence, not just the account"},
        "proportionate": {"type": "integer", "description": "1-5: emphasis matches the size of the variance and its drivers"},
        "actionable": {"type": "integer", "description": "1-5: flags what the owner should do or ask, where relevant"},
        "rationale": {"type": "string"},
    })},
})


def judge_commentary(commentary: Commentary, contexts: dict[str, dict], *, model: str | None = None) -> dict:
    """Rubric scores for qualities the deterministic validator cannot see. Advisory; calibrated against reviewer labels."""
    system = ("You are a senior accountant reviewing variance commentary drafted by a junior. Score strictly against the "
              "rubric using only the evidence provided. A score of 5 means you would send it to the client unchanged.")
    payload = {"commentary": commentary.model_dump(), "evidence_context": contexts}
    _, out = _create([{"role": "user", "content": json.dumps(payload, indent=1)}], system, JUDGE_SCHEMA,
                     model=model or model_name(), effort="medium", max_tokens=8000)
    return out


def available() -> bool:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
                or Path.home().joinpath(".config", "anthropic").exists())
