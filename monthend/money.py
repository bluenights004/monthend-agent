"""Decimal helpers. Floats never touch an accounting figure in this codebase."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

ZERO = Decimal("0")
CENT = Decimal("0.01")


def dec(value: object) -> Decimal:
    """Convert API/CSV/JSON values to Decimal. Floats go through str() to avoid binary noise."""
    if value is None or value == "":
        return ZERO
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        value = repr(value)
    text = str(value).strip().replace(",", "").replace("$", "")
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"not a monetary amount: {value!r}") from exc


def q2(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def pct(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    """Percentage to one decimal place, or None when the base is zero."""
    if denominator == 0:
        return None
    return (numerator / abs(denominator) * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def fmt_money(value: Decimal, currency: str = "") -> str:
    text = f"{abs(q2(value)):,.2f}"
    if text.endswith(".00"):
        text = text[:-3]
    sign = "-" if value < 0 else ""
    return f"{currency} {sign}{text}".strip()


def to_json(value: Decimal | None) -> str | None:
    return None if value is None else str(q2(value))
