"""Behavior guards for the extracted Explorer transfer interaction mixin."""
from types import SimpleNamespace
from unittest.mock import Mock

from WinUx.controllers.explorer_transfer_interaction import ExplorerTransferInteractionMixin


class _Controller(ExplorerTransferInteractionMixin):
    pass


def _panel(panel_id):
    return SimpleNamespace(
        panel_id=panel_id,
        current_path="/target",
        clear_external_drop_highlight=Mock(),
        set_external_drop_highlight_at=Mock(),
        drag_transfer_paths=Mock(return_value=["/source/a.inp"]),
        selected_transfer_paths=Mock(return_value=["/source/a.inp"]),
        status=SimpleNamespace(set=Mock()),
    )


def test_drag_start_resets_cached_target_and_all_highlights():
    controller = _Controller()
    left, right = _panel("local"), _panel("server")
    controller.view = SimpleNamespace(panels=[left, right])
    controller._drag_target_panel = right
    controller._drag_target_destination = "/old"
    controller._drag_target_point = (1, 2)

    controller.drag_start(left)

    assert controller._drag_target_panel is None
    assert controller._drag_target_destination is None
    assert controller._drag_target_point is None
    left.clear_external_drop_highlight.assert_called_once_with()
    right.clear_external_drop_highlight.assert_called_once_with()


def test_drag_motion_caches_only_valid_destination_and_highlights_other_panel():
    controller = _Controller()
    left, right = _panel("local"), _panel("server")
    controller.view = SimpleNamespace(panels=[left, right])
    controller._drag_target_panel = None
    controller._drag_target_destination = None
    controller._drag_target_point = None
    controller._drop_target = Mock(return_value=(right, "/scratch/job", (220, 130)))
    controller._drop_is_valid = Mock(return_value=True)
    controller._destination_display_name = Mock(return_value="job")

    result = controller.drag_motion(left, 220, 130)

    assert result == "job"
    assert controller._drag_target_panel is right
    assert controller._drag_target_destination == "/scratch/job"
    assert controller._drag_target_point == (220.0, 130.0)
    right.set_external_drop_highlight_at.assert_called_once_with(220, 130, True)


def test_drop_with_lost_coordinates_uses_last_visible_cached_target():
    controller = _Controller()
    left, right = _panel("local"), _panel("server")
    controller.view = SimpleNamespace(panels=[left, right], after=Mock())
    controller._drag_target_panel = right
    controller._drag_target_destination = "/scratch/job"
    controller._drag_target_point = (220.0, 130.0)
    controller._drop_target = Mock(return_value=(left, "/local", (0, 0)))
    controller._process_queued_drop = Mock()

    controller.drop(left, 0, 0, True)

    controller.view.after.assert_called_once_with(
        0,
        controller._process_queued_drop,
        left,
        right,
        "/scratch/job",
        True,
        ["/source/a.inp"],
    )
    assert controller._drag_target_panel is None
    assert controller._drag_target_destination is None
    assert controller._drag_target_point is None
