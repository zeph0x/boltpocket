"""
Procedural bolt card graphics generator.
Generates unique SVG card designs seeded from the card UID.
Credit card size: 85.6mm × 54mm (at 96dpi ≈ 323 × 204 px).
"""

import hashlib
import math
import io
import qrcode
import qrcode.image.svg


# Card dimensions in px (at 96 DPI, matches credit card size)
W = 323
H = 204


def _seed_from_uid(uid_hex):
    """Generate a list of deterministic pseudo-random floats from UID."""
    h = hashlib.sha256(uid_hex.encode()).digest()
    # Extend with more hashes for more values
    h2 = hashlib.sha256(h).digest()
    h3 = hashlib.sha256(h2).digest()
    raw = h + h2 + h3
    return [b / 255.0 for b in raw]


def _color_from_seed(vals, offset=0):
    """Generate a vibrant HSL color from seed values."""
    hue = int(vals[offset] * 360)
    sat = 70 + int(vals[offset + 1] * 30)  # 70-100%
    lit = 50 + int(vals[offset + 2] * 20)  # 50-70%
    return f'hsl({hue},{sat}%,{lit}%)'


def _lightning_bolt(cx, cy, size, rotation, color, opacity=0.8):
    """Generate an SVG lightning bolt path."""
    s = size
    # Simple zigzag bolt shape
    points = [
        (0, -s), (s*0.15, -s*0.2), (-s*0.05, -s*0.15),
        (s*0.25, s*0.6), (s*0.05, s*0.1), (s*0.15, s*0.15),
        (-s*0.1, s)
    ]
    path_d = f'M {points[0][0]} {points[0][1]}'
    for p in points[1:]:
        path_d += f' L {p[0]} {p[1]}'
    path_d += ' Z'
    return (
        f'<g transform="translate({cx},{cy}) rotate({rotation})" '
        f'opacity="{opacity}">'
        f'<path d="{path_d}" fill="{color}" />'
        f'</g>'
    )


def _bubble(cx, cy, r, color, opacity):
    """Generate an SVG circle."""
    return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{color}" opacity="{opacity}" />'


def _star(cx, cy, size, points_n, rotation, color, opacity):
    """Generate an SVG star/polygon."""
    pts = []
    for i in range(points_n * 2):
        angle = math.radians(rotation + i * 180 / points_n - 90)
        r = size if i % 2 == 0 else size * 0.4
        pts.append(f'{cx + r * math.cos(angle):.1f},{cy + r * math.sin(angle):.1f}')
    return f'<polygon points="{" ".join(pts)}" fill="{color}" opacity="{opacity}" />'


def _wavy_line(y, amplitude, frequency, color, stroke_width, seed_offset, vals):
    """Generate a wavy SVG path."""
    phase = vals[seed_offset % len(vals)] * math.pi * 2
    d = f'M 0 {y}'
    for x in range(0, W + 5, 5):
        yy = y + amplitude * math.sin(frequency * x * 0.02 + phase)
        d += f' L {x} {yy:.1f}'
    return f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{stroke_width}" opacity="0.5" />'


def generate_front(uid_hex):
    """Generate the front side SVG."""
    vals = _seed_from_uid(uid_hex)

    # Background gradient colors
    bg1 = _color_from_seed(vals, 0)
    bg2 = _color_from_seed(vals, 3)

    elements = []

    # Background gradient
    elements.append(f'''<defs>
        <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" style="stop-color:{bg1}" />
            <stop offset="100%" style="stop-color:{bg2}" />
        </linearGradient>
    </defs>''')
    elements.append(f'<rect width="{W}" height="{H}" rx="12" fill="url(#bg)" />')

    # Scattered bubbles
    for i in range(12):
        idx = (i * 4 + 6) % len(vals)
        cx = vals[idx] * W
        cy = vals[idx + 1] * H
        r = 5 + vals[idx + 2] * 25
        color = _color_from_seed(vals, (i * 3 + 10) % (len(vals) - 3))
        opacity = 0.15 + vals[idx + 3 if idx + 3 < len(vals) else 0] * 0.3
        elements.append(_bubble(cx, cy, r, color, opacity))

    # Wavy lines
    for i in range(4):
        y = 30 + i * 45 + vals[(i * 5 + 20) % len(vals)] * 20
        amp = 8 + vals[(i * 3 + 25) % len(vals)] * 15
        freq = 1 + vals[(i * 3 + 30) % len(vals)] * 3
        color = _color_from_seed(vals, (i * 3 + 40) % (len(vals) - 3))
        elements.append(_wavy_line(y, amp, freq, color, 2.5, i * 7 + 35, vals))

    # Stars
    for i in range(6):
        idx = (i * 5 + 50) % len(vals)
        cx = vals[idx] * W
        cy = vals[idx + 1] * H
        size = 4 + vals[idx + 2] * 12
        n_points = 4 + int(vals[idx + 3 if idx + 3 < len(vals) else 0] * 4)
        rotation = vals[(idx + 4) % len(vals)] * 360
        color = _color_from_seed(vals, (i * 3 + 55) % (len(vals) - 3))
        elements.append(_star(cx, cy, size, n_points, rotation, color, 0.6))

    # Lightning bolts
    for i in range(3):
        idx = (i * 6 + 70) % len(vals)
        cx = 50 + vals[idx] * (W - 100)
        cy = 30 + vals[idx + 1] * (H - 60)
        size = 15 + vals[idx + 2] * 25
        rotation = -20 + vals[idx + 3 if idx + 3 < len(vals) else 0] * 40
        color = '#ffffff'
        elements.append(_lightning_bolt(cx, cy, size, rotation, color, 0.7))

    # BoltPocket text
    elements.append(
        f'<text x="{W - 10}" y="{H - 10}" '
        f'font-family="sans-serif" font-size="11" font-weight="bold" '
        f'fill="white" opacity="0.8" text-anchor="end">⚡ BoltPocket</text>'
    )

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{W}" height="{H}" viewBox="0 0 {W} {H}">\n'
        + '\n'.join(elements) +
        '\n</svg>'
    )
    return svg


def _qr_svg_group(data, x, y, size):
    """Generate a QR code as an SVG group positioned at (x, y) fitting in size×size."""
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=1)
    buf = io.BytesIO()
    img.save(buf)
    svg_str = buf.getvalue().decode()

    # Extract the path d= from the generated SVG
    import re
    # Match the first <path d="..."> which contains the QR data
    path_match = re.search(r'<path\s+d="(M[^"]+)"', svg_str)
    if not path_match:
        return ''
    path_d = path_match.group(1)

    # Get the viewBox to calculate scale (may be decimal/mm)
    vb_match = re.search(r'viewBox="0 0 ([0-9.]+) ([0-9.]+)"', svg_str)
    if vb_match:
        qr_size = float(vb_match.group(1))
    else:
        qr_size = 33

    scale = size / qr_size

    return (
        f'<g transform="translate({x},{y}) scale({scale:.4f})">'
        f'<rect width="{qr_size}" height="{qr_size}" fill="white" rx="2" />'
        f'<path d="{path_d}" fill="black" />'
        f'</g>'
    )


def generate_back(uid_hex, ln_address=None, wallet_url=None):
    """Generate the back side SVG with QR codes."""
    vals = _seed_from_uid(uid_hex)

    elements = []

    # Light background with subtle tint from UID
    hue = int(vals[0] * 360)
    elements.append(f'<rect width="{W}" height="{H}" rx="12" fill="hsl({hue},15%,95%)" />')

    qr_size = 70
    margin = 15

    if ln_address and wallet_url:
        # Two QR codes side by side
        qr1_x = margin + 20
        qr2_x = W - margin - qr_size - 20
        qr_y = (H - qr_size) / 2 - 10

        elements.append(_qr_svg_group(ln_address, qr1_x, qr_y, qr_size))
        elements.append(
            f'<text x="{qr1_x + qr_size / 2}" y="{qr_y + qr_size + 14}" '
            f'font-family="sans-serif" font-size="8" fill="#333" text-anchor="middle">Deposit</text>'
        )

        elements.append(_qr_svg_group(wallet_url, qr2_x, qr_y, qr_size))
        elements.append(
            f'<text x="{qr2_x + qr_size / 2}" y="{qr_y + qr_size + 14}" '
            f'font-family="sans-serif" font-size="8" fill="#333" text-anchor="middle">Balance</text>'
        )
    elif ln_address:
        qr_x = (W - qr_size) / 2
        qr_y = (H - qr_size) / 2 - 10
        elements.append(_qr_svg_group(ln_address, qr_x, qr_y, qr_size))
        elements.append(
            f'<text x="{W / 2}" y="{qr_y + qr_size + 14}" '
            f'font-family="sans-serif" font-size="8" fill="#333" text-anchor="middle">Deposit</text>'
        )

    # UID text at bottom
    formatted_uid = ':'.join(uid_hex[i:i+2] for i in range(0, len(uid_hex), 2))
    elements.append(
        f'<text x="{W / 2}" y="{H - 10}" '
        f'font-family="monospace" font-size="7" fill="#999" text-anchor="middle">{formatted_uid}</text>'
    )

    # BoltPocket branding
    elements.append(
        f'<text x="{W / 2}" y="14" '
        f'font-family="sans-serif" font-size="9" font-weight="bold" fill="#666" text-anchor="middle">⚡ BoltPocket</text>'
    )

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{W}" height="{H}" viewBox="0 0 {W} {H}">\n'
        + '\n'.join(elements) +
        '\n</svg>'
    )
    return svg


def generate_card(uid_hex, ln_address=None, wallet_url=None):
    """Generate both sides. Returns (front_svg, back_svg)."""
    return generate_front(uid_hex), generate_back(uid_hex, ln_address, wallet_url)
