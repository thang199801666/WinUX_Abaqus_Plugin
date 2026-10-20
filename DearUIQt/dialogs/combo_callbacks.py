"""Preserve native callback arity/user_data when a dialog adopts QComboBox."""
import inspect


def adapt_combo_callback(callback, user_data=None):
    if callback is None:
        return None
    if not callable(callback):
        raise TypeError("combo callback must be callable or None")
    count = 3
    try:
        parameters = list(inspect.signature(callback).parameters.values())
        if not any(parameter.kind == inspect.Parameter.VAR_POSITIONAL for parameter in parameters):
            count = min(3, sum(parameter.kind in (
                inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
                for parameter in parameters))
    except (TypeError, ValueError):
        pass

    def changed(sender, value, combo):
        # The old factory returned the control tag, not an internal editor tag.
        # Do not catch callback TypeError here: errors inside callbacks must not
        # cause a second invocation or be mistaken for an arity mismatch.
        return callback(*(combo.tag, value, user_data)[:count])

    return changed
