"""Accessibility-tree handling: parse WDA source XML, normalize, prune, fingerprint.

Pure functions only: no HTTP, no session state, no viewport cache. That keeps the
model-facing node shape and the pruning rules testable without a phone attached.
"""
import math
import xml.etree.ElementTree as ET

TYPE_PREFIX = "XCUIElementType"
# Containers that usually only carry layout; pruned when a specific child repeats them.
GENERIC_CONTAINERS = {"XCUIElementTypeOther", "XCUIElementTypeGroup"}
# The page itself and the window are not targets.
SKIPPED_TYPES = ("XCUIElementTypeApplication", "XCUIElementTypeWindow")
TEXT_FIELDS = ("label", "name", "value")
NODE_FIELDS = ("type", "name", "label", "value", "enabled", "visible")


def parse_source(raw):
    """Split WDA's XML into (application attributes, nodes).

    Rows without any text are skipped unless they are alerts or sheets: those carry
    meaning by existence alone. Geometry is parsed here so one bad rect never aborts
    the whole page. Raises xml.etree.ElementTree.ParseError on malformed XML.
    """
    document = ET.fromstring(raw)
    application = document if document.attrib.get("type") == "XCUIElementTypeApplication" else next(
        (element for element in document.iter() if element.attrib.get("type") == "XCUIElementTypeApplication"), None)
    root = application.attrib if application is not None else {}
    nodes = []
    for element in document.iter():
        attributes = element.attrib
        if not any(attributes.get(key) for key in TEXT_FIELDS) and attributes.get("type") not in ("XCUIElementTypeAlert", "XCUIElementTypeSheet"):
            continue
        try:
            rect = {key: float(attributes.get(key, 0)) for key in ("x", "y", "width", "height")}
        except ValueError:
            continue
        if not all(math.isfinite(value) for value in rect.values()):
            continue
        if attributes.get("type") in SKIPPED_TYPES:
            continue
        node = {key: attributes[key] for key in NODE_FIELDS if key in attributes}
        node["rect"] = rect
        nodes.append(node)
    return root, nodes


def short_type(kind):
    return kind[len(TYPE_PREFIX):] if isinstance(kind, str) and kind.startswith(TYPE_PREFIX) else kind


def compact_node(node):
    """Model-facing node: short type, each distinct text once, integer [x,y,width,height].

    Omitted fields carry their defaults: name equals label, value repeats the text,
    enabled and visible are true, and the node intersects the viewport.
    """
    result = {}
    if node.get("type"):
        result["type"] = short_type(node["type"])
    label, name, value = node.get("label"), node.get("name"), node.get("value")
    if label:
        result["label"] = label
    if name and name != label:
        result["name"] = name
    if value and value != (label or name):
        result["value"] = value
    if node.get("enabled") in ("false", False):
        result["enabled"] = False
    if node.get("visible") in ("false", False):
        result["visible"] = False
    if node.get("in_viewport") is False:
        result["in_viewport"] = False
    rect = node.get("rect")
    if rect:
        result["rect"] = [round(rect[key]) for key in ("x", "y", "width", "height")]
    return result


def contains(outer, inner, slack=1):
    return (outer["x"] - slack <= inner["x"] and outer["y"] - slack <= inner["y"]
            and inner["x"] + inner["width"] <= outer["x"] + outer["width"] + slack
            and inner["y"] + inner["height"] <= outer["y"] + outer["height"] + slack)


def _group_key(node):
    rect = node.get("rect", {})
    return (node.get("label") or node.get("name"), round(rect.get("x", 0)), round(rect.get("y", 0)),
            round(rect.get("width", 0)), round(rect.get("height", 0)))


def prune_nodes(nodes):
    """Drop generic containers that duplicate a specific child's text and geometry."""
    if len(nodes) <= 1:
        return nodes
    specific = {_group_key(node) for node in nodes
                if node.get("type", "") not in GENERIC_CONTAINERS and (node.get("label") or node.get("name"))}
    if not specific:
        return nodes
    kept = []
    for node in nodes:
        if node.get("type", "") in GENERIC_CONTAINERS and (node.get("label") or node.get("name")):
            if _group_key(node) in specific:
                continue
        kept.append(node)
    return kept


def tree_digest(nodes):
    """Stable fingerprint of the visible tree, for "did the screen change yet" checks.

    Only fields that describe the screen are hashed; observation IDs, timestamps and
    image bytes would make the same screen look different on every read.
    """
    if not isinstance(nodes, list):
        return None
    import hashlib

    digest = hashlib.blake2b(digest_size=8)
    for node in nodes:
        if not isinstance(node, dict):
            continue
        # Raw nodes carry a dict rect; compacted model-facing nodes carry [x,y,w,h].
        rect = node.get("rect")
        if isinstance(rect, dict):
            geometry = (rect.get("x"), rect.get("y"), rect.get("width"), rect.get("height"))
        elif isinstance(rect, (list, tuple)):
            geometry = tuple(rect[:4])
        else:
            geometry = None
        digest.update(repr((node.get("type"), node.get("label"), node.get("name"), node.get("value"),
                            node.get("enabled"), node.get("in_viewport"), geometry)).encode())
    return digest.hexdigest()
