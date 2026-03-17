#!/usr/bin/env python3
"""
Generate print-ready card images from CSV.

Usage:
    python scripts/generate_cards.py cards.csv --output-dir card_images/

Generates:
    card_images/<name>_front.png  (85.6 x 54 mm @ 300 DPI)
    card_images/<name>_back.png

Card design:
    Front: Dark gradient, Bitcoin/Lightning branding, cardholder name
    Back: Wallet QR code, Lightning address, BoltPocket branding
"""

import csv
import os
import sys
import argparse
import math

from PIL import Image, ImageDraw, ImageFont
import qrcode

# Credit card dimensions at 300 DPI
# 85.6mm x 54mm = 3.37" x 2.126" → 1011 x 638 px @ 300 DPI
CARD_W = 1011
CARD_H = 638
DPI = 300

# Rounded corner radius
CORNER_R = 30

# Colors
BG_DARK = '#0d1117'
BG_GRADIENT_TOP = '#1a1a2e'
BG_GRADIENT_BOTTOM = '#0d1117'
ORANGE = '#f7931a'
ORANGE_DARK = '#c77614'
WHITE = '#ffffff'
GRAY = '#888888'
LIGHT_GRAY = '#cccccc'

# Fonts
FONT_BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
FONT_REGULAR = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
FONT_MONO = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'


def rounded_rect(draw, xy, radius, fill):
    """Draw a rounded rectangle."""
    x0, y0, x1, y1 = xy
    draw.rectangle([x0 + radius, y0, x1 - radius, y1], fill=fill)
    draw.rectangle([x0, y0 + radius, x1, y1 - radius], fill=fill)
    draw.pieslice([x0, y0, x0 + 2*radius, y0 + 2*radius], 180, 270, fill=fill)
    draw.pieslice([x1 - 2*radius, y0, x1, y0 + 2*radius], 270, 360, fill=fill)
    draw.pieslice([x0, y1 - 2*radius, x0 + 2*radius, y1], 90, 180, fill=fill)
    draw.pieslice([x1 - 2*radius, y1 - 2*radius, x1, y1], 0, 90, fill=fill)


def draw_gradient(img, color_top, color_bottom):
    """Draw a vertical gradient."""
    draw = ImageDraw.Draw(img)
    r1, g1, b1 = int(color_top[1:3], 16), int(color_top[3:5], 16), int(color_top[5:7], 16)
    r2, g2, b2 = int(color_bottom[1:3], 16), int(color_bottom[3:5], 16), int(color_bottom[5:7], 16)
    for y in range(img.height):
        t = y / img.height
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        draw.line([(0, y), (img.width, y)], fill=(r, g, b))


def draw_lightning_bolt(draw, cx, cy, size, color):
    """Draw a stylized lightning bolt."""
    s = size / 100
    points = [
        (cx + 10*s, cy - 50*s),
        (cx - 5*s, cy - 5*s),
        (cx + 15*s, cy - 10*s),
        (cx - 10*s, cy + 50*s),
        (cx + 5*s, cy + 5*s),
        (cx - 15*s, cy + 10*s),
    ]
    draw.polygon(points, fill=color)


def make_qr(data, size=280, fg='#f7931a', bg='#0d1117'):
    """Generate a QR code as PIL Image."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color=fg, back_color=bg).convert('RGB')
    return img.resize((size, size), Image.LANCZOS)


def generate_front(name, output_path):
    """Generate the front of the card."""
    img = Image.new('RGB', (CARD_W, CARD_H))
    draw_gradient(img, BG_GRADIENT_TOP, BG_GRADIENT_BOTTOM)
    draw = ImageDraw.Draw(img)

    # Subtle circuit-like pattern (decorative lines)
    for i in range(0, CARD_W, 60):
        alpha = 20 + (i % 3) * 5
        draw.line([(i, 0), (i, CARD_H)], fill=(255, 255, 255, alpha), width=1)
    for i in range(0, CARD_H, 60):
        alpha = 15 + (i % 3) * 5
        draw.line([(0, i), (CARD_W, i)], fill=(255, 255, 255, alpha), width=1)

    # Large lightning bolt (background decoration)
    draw_lightning_bolt(draw, CARD_W - 180, CARD_H // 2, 250, '#1a1a2e')
    draw_lightning_bolt(draw, CARD_W - 180, CARD_H // 2, 220, '#222244')

    # BoltPocket logo area
    font_logo = ImageFont.truetype(FONT_BOLD, 48)
    draw.text((60, 40), '⚡', fill=ORANGE, font=font_logo)
    draw.text((110, 42), 'BoltPocket', fill=WHITE, font=font_logo)

    # Orange accent line
    draw.rectangle([60, 110, 300, 114], fill=ORANGE)

    # Cardholder name
    font_name = ImageFont.truetype(FONT_BOLD, 52)
    draw.text((60, CARD_H - 130), name, fill=WHITE, font=font_name)

    # Small tagline
    font_small = ImageFont.truetype(FONT_REGULAR, 22)
    draw.text((60, CARD_H - 65), 'Bitcoin · Lightning · NFC', fill=GRAY, font=font_small)

    # Contactless symbol (simplified)
    cx, cy = CARD_W - 80, 70
    for r in [18, 28, 38]:
        draw.arc([cx - r, cy - r, cx + r, cy + r], 220, 320, fill=ORANGE, width=3)

    # NFC chip rectangle
    draw.rounded_rectangle([60, 200, 160, 280], radius=8, outline=LIGHT_GRAY, width=2)
    draw.rounded_rectangle([70, 210, 150, 270], radius=4, outline=LIGHT_GRAY, width=1)
    draw.line([(110, 200), (110, 280)], fill=LIGHT_GRAY, width=1)
    draw.line([(60, 240), (160, 240)], fill=LIGHT_GRAY, width=1)

    img.save(output_path, dpi=(DPI, DPI))
    return img


def generate_back(name, wallet_url, ln_address, output_path):
    """Generate the back of the card."""
    img = Image.new('RGB', (CARD_W, CARD_H))
    draw_gradient(img, '#0d1117', '#0a0a1a')
    draw = ImageDraw.Draw(img)

    # QR code for wallet URL
    qr_size = 320
    qr_img = make_qr(wallet_url, size=qr_size)
    qr_x = (CARD_W - qr_size) // 2
    qr_y = 30
    img.paste(qr_img, (qr_x, qr_y))

    # QR label
    font_small = ImageFont.truetype(FONT_REGULAR, 18)
    label = 'Scan to open wallet'
    bbox = draw.textbbox((0, 0), label, font=font_small)
    label_w = bbox[2] - bbox[0]
    draw.text(((CARD_W - label_w) // 2, qr_y + qr_size + 8), label, fill=GRAY, font=font_small)

    # Lightning address
    font_ln = ImageFont.truetype(FONT_MONO, 20)
    bbox = draw.textbbox((0, 0), ln_address, font=font_ln)
    ln_w = bbox[2] - bbox[0]
    ln_y = qr_y + qr_size + 40
    draw.text(((CARD_W - ln_w) // 2, ln_y), ln_address, fill=ORANGE, font=font_ln)

    # Lightning address label
    font_tiny = ImageFont.truetype(FONT_REGULAR, 16)
    la_label = '⚡ Lightning Address'
    bbox = draw.textbbox((0, 0), la_label, font=font_tiny)
    la_w = bbox[2] - bbox[0]
    draw.text(((CARD_W - la_w) // 2, ln_y + 28), la_label, fill=GRAY, font=font_tiny)

    # Cardholder name (small, bottom)
    font_name = ImageFont.truetype(FONT_BOLD, 24)
    draw.text((60, CARD_H - 55), name, fill=LIGHT_GRAY, font=font_name)

    # Domain branding
    font_brand = ImageFont.truetype(FONT_REGULAR, 18)
    brand = 'your-server.com'
    bbox = draw.textbbox((0, 0), brand, font=font_brand)
    brand_w = bbox[2] - bbox[0]
    draw.text((CARD_W - brand_w - 60, CARD_H - 50), brand, fill=GRAY, font=font_brand)

    img.save(output_path, dpi=(DPI, DPI))
    return img


def main():
    parser = argparse.ArgumentParser(description='Generate card images from CSV')
    parser.add_argument('csv_file', help='Input CSV file from create_wallets')
    parser.add_argument('--output-dir', default='card_images', help='Output directory')
    parser.add_argument('--preview', action='store_true', help='Generate low-res preview')
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    with open(args.csv_file, 'r') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f'Generating {len(rows)} card designs...')
    for row in rows:
        name = row['name']
        wallet_url = row['wallet_url']
        ln_address = row['ln_address']
        safe_name = name.lower().replace(' ', '_')

        front_path = os.path.join(args.output_dir, f'{safe_name}_front.png')
        back_path = os.path.join(args.output_dir, f'{safe_name}_back.png')

        generate_front(name, front_path)
        generate_back(name, wallet_url, ln_address, back_path)

        print(f'  {name}: {front_path}, {back_path}')

    print(f'\nDone! {len(rows) * 2} images in {args.output_dir}/')
    print(f'Card size: {CARD_W}x{CARD_H}px @ {DPI} DPI (85.6x54mm)')


if __name__ == '__main__':
    main()
