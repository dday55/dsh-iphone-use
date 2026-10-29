"""Selector validation and NSPredicate translation.

Every pua_* tool takes the same closed selector shape; this module owns both the
validation messages and the escaping rules, so one predicate bug is fixed once.
"""
from wda_client import WDAError

SELECTOR_FIELDS = {"label", "label_contains", "name", "value", "type", "enabled", "predicate", "index"}


def _fail(code, message, **details):
    raise WDAError(code, message, details=details)


def literal(value):
    """Quote a literal for NSPredicate.

    NSPredicate rejects literal line breaks inside quoted strings, so control
    characters become Unicode escapes; that keeps a backslash-n in user text
    distinguishable from an actual newline.
    """
    return "".join("\\\\" if char == "\\" else "\\'" if char == "'"
                   else f"\\u{ord(char):04x}" if ord(char) < 32 or ord(char) == 127 or char in "\u2028\u2029"
                   else char for char in value)


def predicate(selector):
    if not isinstance(selector, dict) or not selector or set(selector) - SELECTOR_FIELDS:
        _fail("invalid_selector", "Use label/label_contains/name/value/type/enabled, or a standalone PUA predicate; index picks one match.")
    if "index" in selector:
        index = selector["index"]
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index <= 199:
            _fail("invalid_selector", "index must be an integer 0..199 choosing one match in tree order.")
    criteria = {key: value for key, value in selector.items() if key != "index"}
    if not criteria:
        _fail("invalid_selector", "index only chooses among matches; add label, name, value, type or a predicate.")
    if "predicate" in criteria:
        if len(criteria) != 1:
            _fail("invalid_selector", "predicate cannot be mixed with exact fields.")
        result = criteria["predicate"]
        if not isinstance(result, str) or not 1 <= len(result) <= 2000:
            _fail("invalid_selector", "predicate must have 1..2000 characters.")
        return result
    clauses = []
    for key, value in criteria.items():
        if key == "enabled":
            if not isinstance(value, bool) and value not in ("true", "false"):
                _fail("invalid_selector", "enabled must be a boolean or the exact tree string true/false.")
            clauses.append("enabled == " + ("true" if value is True or value == "true" else "false"))
            continue
        if not isinstance(value, str) or not 1 <= len(value) <= 1000:
            _fail("invalid_selector", "Selector fields must be nonempty strings up to 1000 characters.")
        if "\x00" in value:
            _fail("invalid_selector", "Exact selector strings cannot contain NUL; NSPredicate cannot match that character reliably.")
        if key == "type" and not value.startswith("XCUIElementType"):
            value = "XCUIElementType" + value
        escaped = literal(value)
        clauses.append(f"label CONTAINS '{escaped}'" if key == "label_contains" else f"{key} == '{escaped}'")
    return " AND ".join(clauses)
