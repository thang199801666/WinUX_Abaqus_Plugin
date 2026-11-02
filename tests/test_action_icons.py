"""Semantic icon regression: abaqus python tests/test_action_icons.py."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from PIL import Image, ImageDraw
from WinUx.ui.components.action_icons import ACTION_ICONS, action_icon_pixels
from WinUx.ui.components.toolbar import ResourceTextures
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.view import WinUXView


def main():
    view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
    sheet = Image.new('RGB', (540, 210), '#fafafa')
    draw = ImageDraw.Draw(sheet)
    images = set()
    textures = set()
    for i, name in enumerate(sorted(ACTION_ICONS)):
        width, height, pixels = action_icon_pixels(name, 48)
        rgba = bytes(round(value * 255) for value in pixels)
        icon = Image.frombytes('RGBA', (width, height), rgba)
        assert icon.getbbox() is not None
        images.add(rgba)
        texture = ResourceTextures.get(name)
        assert texture and texture == ResourceTextures.get(name)
        textures.add(texture)
        x, y = (i % 3) * 180, (i // 3) * 70
        sheet.paste(icon, (x + 8, y + 4), icon)
        draw.text((x + 62, y + 21), name, fill='#344054')
    assert len(images) == len(textures) == len(ACTION_ICONS)
    assert action_icon_pixels('not-a-semantic-icon') is None
    target = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode' / 'action_icons.png'
    sheet.save(str(target))
    print('PREVIEW', target, flush=True)
    view.request_shutdown()
    view._gui_runtime.destroy()
    print('PASS: distinct glyphs, transparent pixels, native textures, cache reuse', flush=True)


if __name__ == '__main__':
    main()
