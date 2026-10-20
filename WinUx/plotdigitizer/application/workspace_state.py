"""Host-neutral validation for a persisted Plot Digitizer workspace."""
import math


def normalize_workspace_state(state, engine=None):
    if not isinstance(state, dict):
        raise ValueError("Invalid saved workspace.")
    if not state:
        return {}
    if state.get("version") != 1:
        raise ValueError("Unsupported workspace state version.")
    result = dict(state)

    def number(value, name, minimum=None, maximum=None):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("Invalid saved {}.".format(name))
        if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
            raise ValueError("Invalid saved {}.".format(name))
        return float(value)

    def pair(value, name, minimum=None):
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError("Invalid saved {}.".format(name))
        return [number(item, name, minimum) for item in value]

    for key, choices, default in (
        ("tool", ("axes", "manual", "automatic", "data", "settings"), "axes"),
        ("ribbon_tab", ("home", "view"), "home"),
        ("coordinate_mode", ("Chart X/Y", "Image pixels"), "Chart X/Y"),
        ("export_scope", ("All datasets", "Active dataset"), "All datasets"),
    ):
        result[key] = state.get(key, default)
        if result[key] not in choices:
            raise ValueError("Invalid saved {}.".format(key))
    for key, default in (("auto_fit", True), ("edit_enabled", False),
                         ("ribbon_minimized", False), ("export_sort_x", False)):
        result[key] = state.get(key, default)
        if not isinstance(result[key], bool):
            raise ValueError("Invalid saved {}.".format(key))
    result["scale"] = number(state.get("scale", 1), "image scale", 1e-12)
    result["zoom"] = number(state.get("zoom", 1), "zoom", 0.05, 40)
    result["pan"] = pair(state.get("pan", [0, 0]), "pan")
    result["canvas_size"] = pair(state.get("canvas_size", [1, 1]), "canvas size", 1)
    result["reduction_error"] = number(state.get("reduction_error", 0.5), "reduction tolerance", 0, 10)
    result["viewport_size"] = None if state.get("viewport_size") is None else pair(state["viewport_size"], "window size", 1)
    for key in ("dataset_scroll", "settings_scroll"):
        result[key] = number(state.get(key, 0), key, 0)
    anchors = state.get("anchor_text", {})
    if not isinstance(anchors, dict) or any(key not in ("x1", "x2", "y1", "y2") or
                                          not isinstance(value, str) for key, value in anchors.items()):
        raise ValueError("Invalid saved axis editors.")
    result["anchor_text"] = dict(anchors)
    for key in ("dataset_name_text", "point_x_text", "point_y_text", "palette_selection"):
        result[key] = state.get(key)
        if result[key] is not None and not isinstance(result[key], str):
            raise ValueError("Invalid saved {}.".format(key))

    def point_key(value):
        if value is None:
            return None
        if isinstance(value, str):
            source, separator, index = value.partition(":")
            if not separator or not index.isdigit():
                raise ValueError("Invalid saved point selection.")
            value = [source, int(index)]
        if (not isinstance(value, (tuple, list)) or len(value) != 2 or value[0] not in ("auto", "manual") or
                not isinstance(value[1], int) or isinstance(value[1], bool) or value[1] < 0):
            raise ValueError("Invalid saved point selection.")
        if engine is not None:
            engine.point_pixels(*value)
        return list(value)

    result["selected_point"] = point_key(state.get("selected_point"))
    result["grid_current"] = point_key(state.get("grid_current"))
    selected = state.get("selected_rows", [])
    if not isinstance(selected, list):
        raise ValueError("Invalid saved table selection.")
    result["selected_rows"] = [point_key(value) for value in selected]
    if any(value is None for value in result["selected_rows"]):
        raise ValueError("Invalid saved table selection.")
    for key in ("sample_pixel", "cursor_pixel"):
        result[key] = None if state.get(key) is None else pair(state[key], key)
        if engine is not None and result[key] is not None:
            if engine.image is None:
                raise ValueError("Saved cursor/sample coordinates require an image.")
            engine._pixel(*result[key])
    palette = state.get("palette", [])
    if not isinstance(palette, list) or any(not isinstance(color, (list, tuple)) or len(color) != 3 for color in palette):
        raise ValueError("Invalid saved color palette.")
    result["palette"] = [[number(channel, "RGB color", 0, 255) for channel in color] for color in palette]
    modes = (None, "x1", "x2", "y1", "y2", "manual", "delete", "curve", "area")
    result["pick_mode"] = state.get("pick_mode")
    if result["pick_mode"] not in modes:
        raise ValueError("Invalid saved picking mode.")
    sequence = state.get("calibration_sequence", [])
    if not isinstance(sequence, list) or any(key not in ("x1", "x2", "y1", "y2") for key in sequence):
        raise ValueError("Invalid saved calibration sequence.")
    result["calibration_sequence"] = list(sequence)
    disclosures = state.get("disclosures", {})
    if not isinstance(disclosures, dict) or any(key not in ("axes", "advanced", "reduction") or
                                              not isinstance(value, bool) for key, value in disclosures.items()):
        raise ValueError("Invalid saved panel options.")
    result["disclosures"] = dict(disclosures)
    return result
