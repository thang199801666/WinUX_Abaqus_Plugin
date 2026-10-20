from pathlib import Path
from unittest.mock import MagicMock

from DearUIQt import QAbstractSlider, QFrame, QPushButton, QSlider, QToolButton, Qt


ROOT = Path(__file__).resolve().parents[1]


def backend():
    ui = MagicMock()
    ids = iter(range(100, 5000))
    values = {}
    configs = {}

    def create(*args, **kwargs):
        tag = next(ids)
        values[tag] = kwargs.get("default_value", "")
        configs[tag] = dict(kwargs, enabled=kwargs.get("enabled", True), show=True)
        return tag

    for name in (
        "add_button", "add_image_button", "add_slider_int", "add_vslider_int",
        "add_child_window", "add_item_handler_registry",
    ):
        getattr(ui, name).side_effect = create
    ui.get_value.side_effect = lambda tag: values.get(tag, "")
    ui.set_value.side_effect = lambda tag, value: values.__setitem__(tag, value)
    ui.get_item_configuration.side_effect = lambda tag: configs.get(tag, {"enabled": True, "show": True})
    ui.configure_item.side_effect = lambda tag, **kwargs: configs.setdefault(tag, {}).update(kwargs)
    ui.get_item_state.return_value = {}
    ui.does_item_exist.return_value = True
    ui.get_item_parent.return_value = 1
    return ui, values, configs


def test_r73_catalog_exposes_common_qt_style_control_layer():
    import DearUIQt
    assert tuple(map(int, DearUIQt.__version__.split("."))) >= (1, 12, 0)
    for name in (
        "QPushButton", "QToolButton", "QAbstractSlider", "QSlider",
        "QFrame", "QComboBox", "QLineEdit", "QCheckBox", "QProgressBar",
    ):
        assert name in DearUIQt.__all__


def test_qtoolbutton_can_be_native_image_button_with_qt_icon_api():
    ui, _values, configs = backend()
    button = QToolButton("", backend=ui, icon="texture:search", icon_size=(22, 18))
    assert button.icon() == "texture:search"
    assert button.iconSize() == (22, 18)
    ui.add_image_button.assert_called_once()
    args, kwargs = ui.add_image_button.call_args
    assert args[0] == "texture:search"
    assert kwargs["width"] == 22
    assert kwargs["height"] == 18

    button.setIcon("texture:new")
    assert button.icon() == "texture:new"
    assert configs[button.tag]["texture_tag"] == "texture:new"


def test_qabstractslider_actions_and_slider_position_are_qt_style():
    ui, _values, _configs = backend()
    slider = QSlider(
        Qt.Horizontal, minimum=0, maximum=100, value=20,
        single_step=2, page_step=10, backend=ui)
    assert isinstance(slider, QAbstractSlider)
    actions = []
    slider.actionTriggered.connect(actions.append)
    slider.triggerAction(QAbstractSlider.SliderSingleStepAdd)
    assert slider.value() == 22
    slider.triggerAction(QAbstractSlider.SliderPageStepAdd)
    assert slider.value() == 32
    slider.setInvertedControls(True)
    slider.triggerAction(QAbstractSlider.SliderSingleStepAdd)
    assert slider.value() == 30
    assert actions == [
        QAbstractSlider.SliderSingleStepAdd,
        QAbstractSlider.SliderPageStepAdd,
        QAbstractSlider.SliderSingleStepAdd,
    ]


def test_qframe_wraps_native_panel_lifecycle():
    ui, _values, configs = backend()
    frame = QFrame(backend=ui, frame_shape=QFrame.StyledPanel, width=200, height=80)
    assert frame.frameShape() == QFrame.StyledPanel
    frame.setFrameShape(QFrame.NoFrame)
    assert configs[frame.tag]["border"] is False
    frame.setFrameStyle(QFrame.Panel | QFrame.Sunken)
    assert frame.frameShape() == QFrame.Panel
    assert frame.frameShadow() == QFrame.Sunken


def test_winux_high_frequency_controls_migrate_to_dearuiqt_wrappers():
    toolbar = (ROOT / "WinUx" / "ui" / "components" / "toolbar.py").read_text(encoding="utf-8")
    plots = (ROOT / "WinUx" / "ui" / "components" / "job_plots.py").read_text(encoding="utf-8")

    assert "QToolButton" in toolbar
    assert "QPushButton" in toolbar
    assert "QLineEdit" in toolbar
    assert "self.path_button = dpg.add_button" not in toolbar
    assert "self.search_input = dpg.add_input_text" not in toolbar
    assert "self.search_close = dpg.add_button" not in toolbar

    # The Plot panel uses QToolButton for compact icon actions; older builds
    # used QPushButton here. Both must remain within the DearUIQt wrapper API.
    assert "from DearUIQt.widgets import (" in plots
    assert "QCheckBox, QLineEdit, QToolButton" in plots
    assert "button = QToolButton(" in plots
    assert "self.fit_button = dpg.add_button" not in plots
    assert "self.reference_button = dpg.add_button" not in plots
    assert "self.filter_input = dpg.add_input_text" not in plots
    assert "checkbox = dpg.add_checkbox" not in plots
    assert "checkbox = QCheckBox" in plots
