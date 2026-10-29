"""Tuning constants shared by the controller and the observation layer."""

CANDIDATE_LIMIT = 8
# Bounds checks reuse the viewport briefly; an observation or a supplied ID reads it again.
VIEWPORT_TTL = 30
# One typing request stays short; one tool call stops typing at the budget and hands back a token.
TYPING_FREQUENCY = 30
TYPING_PIECE = 200
CALL_BUDGET = 90
DEFAULT_MAX_NODES = 200
INPUT_TTL = 600
# A selector that leads to no action is not retried in other spellings: the error hands back
# the screen so the very next call can act by coordinates.
SELECTOR_FAILURES = ("no_such_element","ambiguous_target","occluded_target","offscreen_target","not_editable","no_focused_field","search_exhausted")
VISUAL_FAILURES = SELECTOR_FAILURES + ("no_scroll_progress","scroll_context_changed","modal_requires_region","blocked_scroll_region","postcondition_failed","input_mismatch",
                                      "element not interactable","element click intercepted","invalid element state","no such element")
