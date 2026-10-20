from unittest.mock import MagicMock

from DearUIQt import (
    QButtonGroup,
    QDialogButtonBox,
    QRadioButton,
    QSlider,
    QTreeItem,
    QTreeView,
    Qt,
)


def backend():
    ui = MagicMock()
    ids = iter(range(100, 5000))
    values = {}
    configs = {}

    def create(*args, **kwargs):
        tag = next(ids)
        default = kwargs.get("default_value", "")
        values[tag] = default
        configs[tag] = dict(kwargs, enabled=kwargs.get("enabled", True), show=True)
        return tag

    for name in (
        "add_group", "add_button", "add_radio_button", "add_slider_int",
        "add_vslider_int", "add_child_window", "add_tree_node", "add_selectable",
        "add_item_handler_registry",
    ):
        getattr(ui, name).side_effect = create
    ui.get_value.side_effect = lambda tag: values.get(tag, "")
    ui.set_value.side_effect = lambda tag, value: values.__setitem__(tag, value)
    ui.get_item_configuration.side_effect = lambda tag: configs.get(tag, {"enabled": True, "show": True})
    ui.configure_item.side_effect = lambda tag, **kwargs: configs.setdefault(tag, {}).update(kwargs)
    ui.get_item_state.return_value = {}
    ui.does_item_exist.return_value = True
    ui.get_item_parent.return_value = 1
    ui.is_mouse_button_double_clicked.return_value = False
    ui.mvMouseButton_Left = 0
    return ui


def test_v8_catalog_is_exported_from_standalone_package():
    import DearUIQt

    assert tuple(map(int, DearUIQt.__version__.split("."))) >= (1, 2, 0)
    for name in (
        "QRadioButton", "QButtonGroup", "QSlider", "QDialogButtonBox",
        "QTreeItem", "QTreeView",
    ):
        assert name in DearUIQt.__all__
        assert getattr(DearUIQt, name) is not None


def test_qslider_clamps_range_and_emits_value_changes():
    ui = backend()
    slider = QSlider(Qt.Horizontal, minimum=0, maximum=10, value=3, backend=ui)
    changed = []
    slider.valueChanged.connect(changed.append)
    slider.setValue(8)
    assert slider.value() == 8
    slider.setValue(99)
    assert slider.value() == 10
    slider.setRange(4, 6)
    assert slider.value() == 6
    assert slider.minimum() == 4
    assert slider.maximum() == 6
    assert changed == [8, 10, 6]


def test_qbutton_group_enforces_exclusive_radio_selection():
    ui = backend()
    one = QRadioButton("One", checked=True, backend=ui)
    two = QRadioButton("Two", backend=ui)
    group = QButtonGroup()
    group.addButton(one, 10)
    group.addButton(two, 20)
    toggles = []
    group.idToggled.connect(lambda button_id, checked: toggles.append((button_id, checked)))

    two.click()
    assert not one.isChecked()
    assert two.isChecked()
    assert group.checkedButton() is two
    assert group.checkedId() == 20
    assert (10, False) in toggles
    assert (20, True) in toggles


def test_qdialogbuttonbox_maps_standard_buttons_to_semantic_signals():
    ui = backend()
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, backend=ui)
    accepted, rejected = [], []
    box.accepted.connect(lambda: accepted.append(True))
    box.rejected.connect(lambda: rejected.append(True))

    ok = box.button(QDialogButtonBox.Ok)
    cancel = box.button(QDialogButtonBox.Cancel)
    assert ok.text() == "OK"
    assert cancel.text() == "Cancel"
    ok.click()
    cancel.click()
    assert accepted == [True]
    assert rejected == [True]
    assert box.standardButton(ok) == QDialogButtonBox.Ok
    assert box.buttonRole(cancel) == QDialogButtonBox.RejectRole


def test_qtreeview_retains_model_selection_and_expand_state():
    ui = backend()
    child = QTreeItem("Child", key="child")
    root = QTreeItem("Root", key="root", children=[child])
    tree = QTreeView([root], backend=ui)
    changed = []
    expanded = []
    tree.currentChanged.connect(changed.append)
    tree.expanded.connect(expanded.append)

    assert tree.setCurrentKey("child")
    assert tree.currentItem() is child
    assert changed == ["child"]
    assert tree.expand("root")
    assert tree.isExpanded("root")
    assert expanded == ["root"]
    assert tree.collapse("root")
    assert not tree.isExpanded("root")


def test_qplaintextedit_uses_one_multiline_native_editor():
    from DearUIQt import QPlainTextEdit

    ui = backend()
    ui.add_input_text.side_effect = lambda *args, **kwargs: 900
    ui.get_value.side_effect = lambda tag: "alpha\nbeta" if tag == 900 else ""
    ui.get_item_configuration.side_effect = lambda tag: {
        "enabled": True, "show": True, "multiline": tag == 900,
    }
    edit = QPlainTextEdit("alpha", backend=ui, width=320, height=120)
    assert edit.tag == 900
    assert edit.toPlainText() == "alpha\nbeta"
    kwargs = ui.add_input_text.call_args.kwargs
    assert kwargs["multiline"] is True
    assert kwargs["height"] == 120
