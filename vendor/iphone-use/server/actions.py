"""Gesture geometry: default scroll region, safe-area clamping, containment checks.

Kept free of transport and state so the numbers behind a swipe can be asserted in
tests instead of discovered on a phone.
"""
# iOS chrome a gesture must not start in: pulling down opens Notification Center,
# reaching the bottom edge triggers the Home Indicator.
SAFE_TOP = 60.0
SAFE_BOTTOM = 45.0
SAFE_SIDE = 15.0
DRAG_RATIO = 0.32


def default_region(viewport):
    """Central area used when the caller names no region."""
    return {"x": viewport["width"] * .15, "y": viewport["height"] * .25,
            "width": viewport["width"] * .7, "height": viewport["height"] * .5}


def contains_rect(outer, inner):
    return (outer["x"] >= inner["x"] and outer["y"] >= inner["y"]
            and outer["x"] + outer["width"] <= inner["x"] + inner["width"]
            and outer["y"] + outer["height"] <= inner["y"] + inner["height"])


def safe_limits(viewport):
    """Clamp distances scaled to the screen so small phones keep usable margins."""
    width, height = viewport["width"], viewport["height"]
    return {"top": min(SAFE_TOP, height * .1), "bottom": min(SAFE_BOTTOM, height * .1),
            "side": min(SAFE_SIDE, width * .05)}


def swipe_points(region, viewport, direction):
    """Finger path for one direction, clamped clear of the system gesture areas."""
    center_x = region["x"] + region["width"] / 2
    center_y = region["y"] + region["height"] / 2
    delta_x = region["width"] * DRAG_RATIO
    delta_y = region["height"] * DRAG_RATIO
    raw = {"up": (center_x, center_y + delta_y, center_x, center_y - delta_y),
           "down": (center_x, center_y - delta_y, center_x, center_y + delta_y),
           "left": (center_x + delta_x, center_y, center_x - delta_x, center_y),
           "right": (center_x - delta_x, center_y, center_x + delta_x, center_y)}[direction]
    limits = safe_limits(viewport)
    width, height = viewport["width"], viewport["height"]
    from_x, from_y, to_x, to_y = raw
    from_x = max(limits["side"], min(width - limits["side"], from_x))
    to_x = max(limits["side"], min(width - limits["side"], to_x))
    from_y = max(limits["top"], min(height - limits["bottom"], from_y))
    to_y = max(limits["top"], min(height - limits["bottom"], to_y))
    return (from_x, from_y, to_x, to_y)
