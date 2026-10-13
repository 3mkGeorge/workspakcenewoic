"""Centralized input validation and security sanitization services for StorePro.

Provides standard validators for money/cents, integer bounds, required text length,
and Excel/CSV DDE formula injection sanitization and escaping.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def cents(value, label="Enter a valid non-negative amount, up to 1 billion."):
    """Convert floating-point / decimal money string to integer cents with rounding."""
    try:
        d = Decimal(str(value))
        if not d.is_finite() or d < 0 or d > 1000000000:
            raise ValueError()
        return int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(label)


def integer(value, minimum=0, maximum=1000000, label=None):
    """Validate and parse an integer within specified bounds."""
    try:
        result = int(str(value))
        if not minimum <= result <= maximum:
            raise ValueError()
        return result
    except (ValueError, TypeError):
        if label:
            raise ValueError(label)
        raise ValueError(f"Enter a whole number between {minimum} and {maximum}.")


def required(value, label, limit=160):
    """Enforce non-empty string and character length limit."""
    val = (value or "").strip()
    if not val or len(val) > limit:
        raise ValueError(f"{label} is required (maximum {limit} characters).")
    return val


def sanitize_formula(val):
    """Strip dangerous leading formula trigger prefixes (=, +, -, @, \\t, \\r)."""
    if not val:
        return ""
    s = str(val).strip()
    while s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        s = s[1:].strip()
    return s


def escape_formula(val):
    """Prepend single quote to strings starting with formula characters for safe spreadsheet exports."""
    s = str(val or "")
    if s.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + s
    return s
