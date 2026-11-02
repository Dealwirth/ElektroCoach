"""Deterministic calculation and unit handling for calculation tasks.

Requirement: "Bei Rechenaufgaben müssen Ergebnisse zusätzlich mit
deterministischen Berechnungen überprüft werden."

The evaluator is deliberately small and safe: it parses the expression with
:mod:`ast` and only allows arithmetic, a whitelist of mathematical functions and
the variable names supplied by the caller. No ``eval`` of arbitrary code, no
attribute access, no imports.
"""

from __future__ import annotations

import ast
import math
import operator
import re
from dataclasses import dataclass

_ALLOWED_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}

_ALLOWED_UNARY = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_ALLOWED_FUNCTIONS = {
    "sqrt": math.sqrt,
    "abs": abs,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "round": round,
    "min": min,
    "max": max,
}

_ALLOWED_CONSTANTS = {"pi": math.pi, "e": math.e}

# Unit table. Factor converts the unit into the SI base of its dimension.
UNITS: dict[str, tuple[str, float]] = {
    # voltage
    "v": ("V", 1.0), "kv": ("V", 1000.0), "mv": ("V", 0.001),
    # current
    "a": ("A", 1.0), "ma": ("A", 0.001), "ka": ("A", 1000.0),
    # resistance / impedance
    "ohm": ("Ω", 1.0), "ω": ("Ω", 1.0), "kohm": ("Ω", 1000.0), "kω": ("Ω", 1000.0),
    "mohm": ("Ω", 1e6), "mω": ("Ω", 1e6),
    # power
    "w": ("W", 1.0), "kw": ("W", 1000.0), "mw": ("W", 0.001),
    "va": ("VA", 1.0), "kva": ("VA", 1000.0),
    "var": ("var", 1.0), "kvar": ("var", 1000.0),
    # energy
    "wh": ("Wh", 1.0), "kwh": ("Wh", 1000.0), "j": ("J", 1.0),
    # length
    "m": ("m", 1.0), "km": ("m", 1000.0), "cm": ("m", 0.01), "mm": ("m", 0.001),
    # area
    "m2": ("m²", 1.0), "mm2": ("m²", 1e-6), "cm2": ("m²", 1e-4),
    # angle / frequency / misc
    "°": ("°", 1.0), "grad": ("°", 1.0), "hz": ("Hz", 1.0), "khz": ("Hz", 1000.0),
    "s": ("s", 1.0), "min": ("s", 60.0), "h": ("s", 3600.0),
    "%": ("%", 1.0),
}

_UNIT_PATTERN = re.compile(
    r"^\s*(?P<number>[+-]?\d+(?:[.,]\d+)*(?:[eE][+-]?\d+)?)\s*"
    r"(?P<unit>[A-Za-zµμ°Ωω%²³/]{0,6})\s*$"
)

# A numeric literal inside an expression, e.g. "1.500", "12,5", "0,5e3".
_NUMBER_TOKEN = re.compile(r"\d+(?:[.,]\d+)*")

# Groups of exactly three digits after a separator are German thousands
# separators ("1.500" = 1500, "1.500.000" = 1500000), not a decimal fraction.
_THOUSANDS_GROUP = re.compile(r"^\d{1,3}(?:[.\s]\d{3})+$")


def normalise_number_token(token: str) -> str:
    """Convert a German- or English-formatted number to a plain float string.

    Both ``1.500,5`` (German) and ``1,500.5`` (English) become ``1500.5``, while
    ``12,5`` and ``12.5`` become ``12.5``. Without this, ``1.500 W`` would be read
    as 1.5 W, which would silently mark correct answers as wrong.
    """

    text = str(token).strip()
    if not text:
        return text

    if "," in text and "." in text:
        # The separator that appears last is the decimal separator.
        if text.rfind(",") > text.rfind("."):
            return text.replace(".", "").replace(",", ".")
        return text.replace(",", "")

    if "," in text:
        if text.count(",") == 1:
            return text.replace(",", ".")
        return text.replace(",", "")

    if "." in text:
        if _THOUSANDS_GROUP.match(text):
            return text.replace(".", "")
        return text

    return text


def normalise_numeric_literals(expression: str) -> str:
    """Apply :func:`normalise_number_token` to every literal in an expression."""

    return _NUMBER_TOKEN.sub(lambda match: normalise_number_token(match.group(0)),
                             expression)


class CalculationError(ValueError):
    """The expression or the submitted answer could not be interpreted."""


def safe_eval(expression: str, variables: dict[str, float] | None = None) -> float:
    """Evaluate a mathematical expression safely."""

    if expression is None or str(expression).strip() == "":
        raise CalculationError("Der Rechenausdruck ist leer.")
    normalised = (
        str(expression)
        .replace("^", "**")
        .replace("·", "*")
        .replace("×", "*")
        .replace("÷", "/")
        .replace("−", "-")
    )
    # German and English number formats are both accepted; the literals are
    # normalised before parsing so "1.500" means 1500, not 1.5.
    normalised = normalise_numeric_literals(normalised)
    normalised = re.sub(r"(?<=\d)\s*(?=[a-zA-Z_])", "*", normalised)
    try:
        tree = ast.parse(normalised, mode="eval")
    except SyntaxError as exc:
        raise CalculationError(f"Der Rechenausdruck ist ungültig: {expression}") from exc

    names = dict(_ALLOWED_CONSTANTS)
    if variables:
        names.update({k: float(v) for k, v in variables.items()})
    return _eval_node(tree.body, names)


def _eval_node(node: ast.AST, names: dict[str, float]) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            raise CalculationError("Wahrheitswerte sind nicht erlaubt.")
        if isinstance(node.value, (int, float)):
            return float(node.value)
        raise CalculationError(f"Unerlaubter Wert: {node.value!r}")
    if isinstance(node, ast.BinOp):
        handler = _ALLOWED_BINARY.get(type(node.op))
        if handler is None:
            raise CalculationError("Dieser Rechenoperator ist nicht erlaubt.")
        left = _eval_node(node.left, names)
        right = _eval_node(node.right, names)
        if isinstance(node.op, ast.Pow) and abs(right) > 64:
            raise CalculationError("Der Exponent ist zu groß.")
        try:
            return float(handler(left, right))
        except ZeroDivisionError as exc:
            raise CalculationError("Division durch Null.") from exc
    if isinstance(node, ast.UnaryOp):
        handler = _ALLOWED_UNARY.get(type(node.op))
        if handler is None:
            raise CalculationError("Dieser Operator ist nicht erlaubt.")
        return float(handler(_eval_node(node.operand, names)))
    if isinstance(node, ast.Name):
        if node.id in names:
            return float(names[node.id])
        raise CalculationError(f"Unbekannte Größe: {node.id}")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise CalculationError("Funktionsaufrufe dieser Art sind nicht erlaubt.")
        function = _ALLOWED_FUNCTIONS.get(node.func.id)
        if function is None:
            raise CalculationError(f"Unbekannte Funktion: {node.func.id}")
        args = [_eval_node(arg, names) for arg in node.args]
        try:
            return float(function(*args))
        except (TypeError, ValueError, ZeroDivisionError) as exc:
            raise CalculationError(f"Fehler in der Funktion {node.func.id}: {exc}") from exc
    raise CalculationError("Der Rechenausdruck enthält nicht erlaubte Elemente.")


@dataclass
class ParsedValue:
    value: float
    unit: str | None
    base_unit: str | None
    si_value: float
    raw: str


def parse_value(text: str) -> ParsedValue:
    """Parse ``"12,5 A"`` or ``"4.7kΩ"`` into a number plus unit."""

    if text is None:
        raise CalculationError("Es wurde kein Wert angegeben.")
    raw = str(text).strip()
    if raw == "":
        raise CalculationError("Es wurde kein Wert angegeben.")

    # A pure expression without a unit.
    match = _UNIT_PATTERN.match(raw)
    if match:
        number = float(normalise_number_token(match.group("number")))
        unit_raw = (match.group("unit") or "").strip()
        if not unit_raw:
            return ParsedValue(number, None, None, number, raw)
        key = unit_raw.lower().replace("µ", "m").replace("μ", "m")
        key = key.replace("²", "2").replace("³", "3")
        if key in UNITS:
            base, factor = UNITS[key]
            return ParsedValue(number, unit_raw, base, number * factor, raw)
        # Unknown unit: keep the number, report the unit as-is.
        return ParsedValue(number, unit_raw, unit_raw, number, raw)

    # Try to evaluate as an expression (e.g. "230 / 0.5").
    try:
        value = safe_eval(raw)
    except CalculationError as exc:
        raise CalculationError(
            f"Der Wert „{raw}“ konnte nicht als Zahl gelesen werden."
        ) from exc
    return ParsedValue(value, None, None, value, raw)


def check_numeric(answer: str, expected: float, *, unit: str | None = None,
                  tolerance_absolute: float | None = None,
                  tolerance_relative: float = 0.01) -> tuple[bool, str]:
    """Compare a submitted value with the expected value.

    Unit-aware: a submitted value with a compatible unit is converted to the
    expected unit before comparison, so ``0,5 kV`` matches ``500 V``.
    """

    parsed = parse_value(answer)
    submitted = parsed.value
    submitted_base = parsed.si_value
    expected_base = expected

    note = ""
    if unit and parsed.unit:
        target = UNITS.get(unit.lower().replace("²", "2").replace("³", "3"))
        if target is not None and parsed.base_unit is not None:
            if parsed.base_unit != target[0]:
                return False, (
                    f"Die Einheit passt nicht: erwartet wurde {unit}, "
                    f"angegeben wurde {parsed.unit}."
                )
            submitted_base = parsed.si_value
            expected_base = expected * target[1]
            note = f" ({parsed.raw} = {parsed.si_value:g} {target[0]})"
        elif parsed.base_unit == (parsed.unit or "").lower():
            # Unknown unit, compare raw numbers.
            submitted_base = submitted
            expected_base = expected

    difference = abs(submitted_base - expected_base)
    absolute = tolerance_absolute
    if absolute is None:
        absolute = max(abs(expected_base) * tolerance_relative, 1e-9)
    if difference <= absolute:
        return True, f"Der Wert ist korrekt (Abweichung {difference:.4g}).{note}"
    return False, (
        f"Der Wert ist nicht korrekt. Erwartet: {expected:g} {unit or ''}"
        f" (Abweichung {difference:.4g}, erlaubt {absolute:.4g}).{note}"
    )
