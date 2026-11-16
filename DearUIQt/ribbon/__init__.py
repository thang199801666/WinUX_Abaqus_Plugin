"""Office-style ribbon widgets for DearUIQt."""
from .bar import RibbonBar
from .renderers import RibbonTabRenderer
from .layout import RibbonLayout, RibbonGroupLayout, RibbonAdaptiveLayout, RibbonLayoutEngine
from .components import RibbonTab, RibbonContextGroup, RibbonGroup, RibbonButton, RibbonMenuButton, RibbonSplitButton
from .visual_styles import (
    RibbonVisualStyle, RibbonVisualStyleFactory, register_ribbon_visual_style,
    get_ribbon_visual_style, ribbon_visual_style_names, CLASSIC_VISUAL_STYLE,
    CLEAN_VISUAL_STYLE, SOFT_VISUAL_STYLE, FLAT_VISUAL_STYLE,
    MINIMAL_VISUAL_STYLE, HIGH_CONTRAST_VISUAL_STYLE,
)
from .display_templates import (
    RibbonAdaptivePolicy, RibbonDisplayTemplate, RibbonDisplayTemplateFactory,
    register_ribbon_display_template, get_ribbon_display_template,
    ribbon_display_template_names, CLASSIC_DISPLAY_TEMPLATE,
    BALANCED_DISPLAY_TEMPLATE, COMPACT_DISPLAY_TEMPLATE, DENSE_DISPLAY_TEMPLATE,
    LARGE_ICONS_DISPLAY_TEMPLATE, TOUCH_DISPLAY_TEMPLATE, MINIMAL_DISPLAY_TEMPLATE,
)
from .appearance_templates import (
    RibbonAppearanceTemplate, RibbonAppearanceTemplateFactory,
    register_ribbon_appearance_template, get_ribbon_appearance_template,
    ribbon_appearance_template_names, TAB_RENDER_STYLES, GROUP_RENDER_STYLES,
    BUTTON_RENDER_STYLES, CLASSIC_OFFICE_APPEARANCE, MODERN_CLEAN_APPEARANCE,
    SOFT_CARD_APPEARANCE, COMPACT_FLAT_APPEARANCE, DENSE_OUTLINE_APPEARANCE,
    TOUCH_SOFT_APPEARANCE, MINIMAL_APPEARANCE, HIGH_CONTRAST_APPEARANCE,
    TOPLINE_CLEAN_APPEARANCE, SIDE_ACCENT_DENSE_APPEARANCE,
)
from .gallery import (
    RibbonAppearancePreview, RibbonAppearanceSnapshot,
    RibbonAppearanceGalleryView, RibbonAppearanceGallery,
)
from .templates import (
    RibbonCommandTemplate, RibbonGroupTemplate, RibbonTabTemplate, RibbonTemplate,
    RibbonTemplateInstance, RibbonTemplateFactory, register_ribbon_template,
    get_ribbon_template, ribbon_template_names, apply_ribbon_template,
    create_ribbon_from_template, OFFICE_DATA_TEMPLATE, DOCUMENT_TEMPLATE,
    DATA_ANALYSIS_TEMPLATE, PLOT_WORKBENCH_TEMPLATE,
)

__all__ = [
    "RibbonBar", "RibbonTabRenderer", "RibbonTab", "RibbonContextGroup", "RibbonGroup", "RibbonButton", "RibbonMenuButton",
    "RibbonSplitButton", "RibbonLayout", "RibbonGroupLayout", "RibbonAdaptiveLayout", "RibbonLayoutEngine",
    "RibbonVisualStyle", "RibbonVisualStyleFactory", "register_ribbon_visual_style",
    "get_ribbon_visual_style", "ribbon_visual_style_names", "CLASSIC_VISUAL_STYLE",
    "CLEAN_VISUAL_STYLE", "SOFT_VISUAL_STYLE", "FLAT_VISUAL_STYLE",
    "MINIMAL_VISUAL_STYLE", "HIGH_CONTRAST_VISUAL_STYLE",
    "RibbonAppearanceTemplate", "RibbonAppearanceTemplateFactory",
    "register_ribbon_appearance_template", "get_ribbon_appearance_template",
    "ribbon_appearance_template_names", "TAB_RENDER_STYLES", "GROUP_RENDER_STYLES",
    "BUTTON_RENDER_STYLES", "CLASSIC_OFFICE_APPEARANCE", "MODERN_CLEAN_APPEARANCE",
    "SOFT_CARD_APPEARANCE", "COMPACT_FLAT_APPEARANCE", "DENSE_OUTLINE_APPEARANCE",
    "TOUCH_SOFT_APPEARANCE", "MINIMAL_APPEARANCE", "HIGH_CONTRAST_APPEARANCE",
    "TOPLINE_CLEAN_APPEARANCE", "SIDE_ACCENT_DENSE_APPEARANCE",
    "RibbonAppearancePreview", "RibbonAppearanceSnapshot",
    "RibbonAppearanceGalleryView", "RibbonAppearanceGallery",
    "RibbonAdaptivePolicy", "RibbonDisplayTemplate", "RibbonDisplayTemplateFactory",
    "register_ribbon_display_template", "get_ribbon_display_template",
    "ribbon_display_template_names", "CLASSIC_DISPLAY_TEMPLATE",
    "BALANCED_DISPLAY_TEMPLATE", "COMPACT_DISPLAY_TEMPLATE", "DENSE_DISPLAY_TEMPLATE",
    "LARGE_ICONS_DISPLAY_TEMPLATE", "TOUCH_DISPLAY_TEMPLATE", "MINIMAL_DISPLAY_TEMPLATE",
    "RibbonCommandTemplate", "RibbonGroupTemplate", "RibbonTabTemplate",
    "RibbonTemplate", "RibbonTemplateInstance", "RibbonTemplateFactory",
    "register_ribbon_template", "get_ribbon_template", "ribbon_template_names",
    "apply_ribbon_template", "create_ribbon_from_template",
    "OFFICE_DATA_TEMPLATE", "DOCUMENT_TEMPLATE", "DATA_ANALYSIS_TEMPLATE",
    "PLOT_WORKBENCH_TEMPLATE",
]
