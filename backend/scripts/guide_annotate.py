import json
from PIL import Image, ImageDraw, ImageFont

OUT = "/tmp/shots"
RED = (231, 54, 60)
NAVY = (13, 37, 69)
WHITE = (255, 255, 255)
meta = json.load(open(f"{OUT}/meta.json"))

FONT = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


def font(sz):
    return ImageFont.truetype(FONT, sz)


# Per-image vertical crop (top, bottom) in image px; tuned from review.
CROPS = {
    "an_01_rooms": (360, 1760),
    "an_02_studios": (150, 1980),
    "an_03_reserve": (300, 1900),
    "an_04_details": (150, 1995),
    "an_05_payment": (40, 1995),
    "an_06_staff": (300, 1980),
    "an_07_staff_booking": (720, 1995),
    "an_08_apply": (40, 1760),
}

# Optional horizontal crop (left, right) to drop irrelevant dead space.
WCROPS = {
    "an_07_staff_booking": (1838, 2770),
}


def rounded(draw, box, r, **kw):
    draw.rounded_rectangle(box, radius=r, **kw)


def text_size(draw, s, f):
    l, t, rr, b = draw.textbbox((0, 0), s, font=f)
    return rr - l, b - t


def draw_arrow(draw, x0, y0, x1, y1, color, w=7):
    draw.line([(x0, y0), (x1, y1)], fill=color, width=w)
    import math
    ang = math.atan2(y1 - y0, x1 - x0)
    L = 26
    for da in (-0.5, 0.5):
        draw.line([(x1, y1), (x1 - L * math.cos(ang - da), y1 - L * math.sin(ang - da))],
                  fill=color, width=w)


def annotate(name):
    src = f"{OUT}/{name}.png"
    im = Image.open(src).convert("RGB")
    W, H = im.size
    d = ImageDraw.Draw(im)
    lf = font(30)
    nf = font(34)

    for a in meta[name]["anns"]:
        x, y, w, h = a["bbox"]
        cx, cy = x + w / 2, y + h / 2
        # highlight box
        rounded(d, [x - 8, y - 8, x + w + 8, y + h + 8], 14, outline=RED, width=6)

        side = a.get("side", "left")
        label = a["label"]
        tw, th = text_size(d, label, lf)
        pad = 16
        bw, bh = tw + 2 * pad, th + 2 * pad
        gap = 90
        if side == "left":
            bx, by = x - gap - bw, cy - bh / 2
            ax0, ay0, ax1, ay1 = bx + bw, by + bh / 2, x - 10, cy
        elif side == "right":
            bx, by = x + w + gap, cy - bh / 2
            ax0, ay0, ax1, ay1 = bx, by + bh / 2, x + w + 10, cy
        elif side == "top":
            bx, by = cx - bw / 2, y - gap - bh
            ax0, ay0, ax1, ay1 = cx, by + bh, cx, y - 10
        else:  # bottom
            bx, by = cx - bw / 2, y + h + gap
            ax0, ay0, ax1, ay1 = cx, by, cx, y + h + 10
        # clamp horizontally
        bx = max(20, min(bx, W - bw - 20))
        by = max(20, min(by, H - bh - 20))
        # arrow first (under label)
        draw_arrow(d, ax0, ay0, ax1, ay1, RED)
        # label pill
        rounded(d, [bx, by, bx + bw, by + bh], 12, fill=WHITE, outline=RED, width=4)
        d.text((bx + pad, by + pad), label, fill=NAVY, font=lf)

        # number badge at top-left corner of the highlight
        n = a.get("n")
        if n is not None:
            r = 30
            bxc, byc = x - 8, y - 8
            d.ellipse([bxc - r, byc - r, bxc + r, byc + r], fill=RED, outline=WHITE, width=4)
            ns = str(n)
            nw, nh = text_size(d, ns, nf)
            d.text((bxc - nw / 2, byc - nh / 2 - 4), ns, fill=WHITE, font=nf)

    # crop
    top, bot = CROPS.get(name, (0, H))
    left, right = WCROPS.get(name, (0, W))
    im = im.crop((left, top, right, min(bot, H)))
    # thin outer border
    d2 = ImageDraw.Draw(im)
    d2.rectangle([0, 0, im.size[0] - 1, im.size[1] - 1], outline=(210, 214, 220), width=3)
    out = f"{OUT}/ann_{name}.png"
    im.save(out)
    print("wrote", out, im.size)


for k in meta:
    annotate(k)
print("done")
