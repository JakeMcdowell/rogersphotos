# watermark.py
import os, base64, tempfile, math
from PIL import Image, ImageDraw, ImageFont, ImageFilter

WATERMARK_TEXT = "Rogers Photography"

# --- Folders for standalone/batch mode (env overrides for flexibility) ---
INPUT_FOLDER = os.getenv("WM_INPUT_FOLDER", "static/images/originals")
OUTPUT_FOLDER = os.getenv("WM_OUTPUT_FOLDER", "static/images/watermarked")

# Read font index (Bold in TTC is often 1)
FONT_INDEX = int(os.getenv("WATERMARK_FONT_INDEX", "1"))

# Optional fallback (OFL font committed to repo if you want)
FALLBACK_FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "GreatVibes-Regular.ttf")

# Decode TTC from env to a temp file once
_DECODED_FONT_PATH = None
_font_b64 = os.getenv("WATERMARK_FONT_B64", "")
if _font_b64:
    try:
        tmpdir = tempfile.gettempdir()
        _DECODED_FONT_PATH = os.path.join(tmpdir, "snell_roundhand.ttc")
        if not os.path.exists(_DECODED_FONT_PATH):
            with open(_DECODED_FONT_PATH, "wb") as f:
                f.write(base64.b64decode(_font_b64))
    except Exception:
        _DECODED_FONT_PATH = None  # fall back below

# --- Shadow/text settings ---
SHADOW_OPACITY = 80
SHADOW_OFFSET_DISTANCE = 10
SHADOW_ANGLE_DEGREES = -90
SHADOW_BLUR_RADIUS = 20
TEXT_FILL = (255, 255, 255, 160)

def load_snell_font(size: int) -> ImageFont.FreeTypeFont:
    # Try decoded TTC first
    if _DECODED_FONT_PATH and os.path.exists(_DECODED_FONT_PATH):
        try:
            return ImageFont.truetype(_DECODED_FONT_PATH, size=size, index=FONT_INDEX)
        except OSError:
            try:
                return ImageFont.truetype(_DECODED_FONT_PATH, size=size, index=0)
            except OSError:
                pass
    # Fallback to bundled OFL font if you add one to repo
    if os.path.exists(FALLBACK_FONT_PATH):
        return ImageFont.truetype(FALLBACK_FONT_PATH, size=size)
    # Last resort
    return ImageFont.load_default()

def find_max_font_size(text, image_width):
    size = 200
    while size > 1:
        font = load_snell_font(size)
        dummy = Image.new("RGBA", (100, 100))
        draw = ImageDraw.Draw(dummy)
        bbox = draw.textbbox((0, 0), text, font=font)
        if (bbox[2] - bbox[0]) <= image_width - 20:
            return font
        size -= 1
    return load_snell_font(10)

def apply_watermark(input_path, output_path):
    image = Image.open(input_path).convert("RGBA")
    base = image.copy()

    font = find_max_font_size(WATERMARK_TEXT, image.width)

    tmp_draw = ImageDraw.Draw(Image.new("RGBA", image.size))
    bbox = tmp_draw.textbbox((0, 0), WATERMARK_TEXT, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    # Bottom-right with padding
    PADDING = 20
    x = image.width - text_w - PADDING
    y = image.height - text_h - PADDING

    # Shadow offset
    theta = math.radians(SHADOW_ANGLE_DEGREES)
    dx = int(round(SHADOW_OFFSET_DISTANCE * math.cos(theta)))
    dy = int(round(SHADOW_OFFSET_DISTANCE * math.sin(theta)))

    # Shadow layer
    shadow_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow_layer).text(
        (x + dx, y + dy), WATERMARK_TEXT, font=font, fill=(0, 0, 0, SHADOW_OPACITY)
    )
    shadow_blurred = shadow_layer.filter(ImageFilter.GaussianBlur(radius=SHADOW_BLUR_RADIUS))

    # Composite shadow
    composed = Image.alpha_composite(base, shadow_blurred)

    # Text layer (stroke can “thicken” fallback fonts)
    text_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    text_draw = ImageDraw.Draw(text_layer)
    text_draw.text(
        (x, y),
        WATERMARK_TEXT,
        font=font,
        fill=TEXT_FILL,
        stroke_width=1,
        stroke_fill=TEXT_FILL
    )

    composed = Image.alpha_composite(composed, text_layer)
    composed.convert("RGB").save(output_path, "JPEG", quality=95)

# --- Optional: quick debug helpers you can import from app.py ---
def font_debug_info():
    return {
        "decoded_font_path": _DECODED_FONT_PATH,
        "decoded_exists": bool(_DECODED_FONT_PATH and os.path.exists(_DECODED_FONT_PATH)),
        "font_index": FONT_INDEX,
        "fallback_exists": os.path.exists(FALLBACK_FONT_PATH),
        "input_folder": INPUT_FOLDER,
        "output_folder": OUTPUT_FOLDER,
    }

# --- Standalone batch mode (for local use) ---
if __name__ == "__main__":
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    if not os.path.isdir(INPUT_FOLDER):
        print(f"[watermark] INPUT_FOLDER not found: {INPUT_FOLDER}")
    else:
        for filename in os.listdir(INPUT_FOLDER):
            if filename.lower().endswith((".jpg", ".jpeg", ".png")):
                input_path = os.path.join(INPUT_FOLDER, filename)
                output_path = os.path.join(OUTPUT_FOLDER, filename)
                apply_watermark(input_path, output_path)
                print(f"Watermarked: {filename}")
