"""Regenerate the neutral geometric icon; optional Pillow development utility."""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def main():
    target = ROOT / "custom_components/itho_spider/brand"
    target.mkdir(exist_ok=True)
    for size, name in ((256, "icon.png"), (512, "icon@2x.png")):
        canvas = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle((0, 0, 255, 255), radius=48, fill="#123840")
        draw.rounded_rectangle((96, 34, 150, 186), radius=27, fill="#F3F6F4")
        draw.ellipse((80, 158, 166, 244), fill="#F3F6F4")
        draw.rounded_rectangle((113, 72, 133, 198), radius=10, fill="#38D3AF")
        draw.ellipse((98, 176, 148, 226), fill="#38D3AF")
        for y in (70, 100, 130):
            draw.rounded_rectangle((164, y, 192, y + 7), radius=3, fill="#F3F6F4")
        canvas.resize((size, size), Image.Resampling.LANCZOS).save(target / name, optimize=True)


if __name__ == "__main__":
    main()
