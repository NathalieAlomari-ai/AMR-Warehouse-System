"""
Generates two QR code images for testing the full vision pipeline.

  shelf_qr.png  — hold this in front of the camera first (Stage 1)
  box_qr.png    — hold this in front of the camera second (Stage 2 + Stage 3)

Run:
    python scripts/generate_test_qr.py
Then open both PNG files on your screen or print them.
"""

import qrcode
from pathlib import Path

SHELF_ID  = "SHELF-A1"
BOX_SKU   = "BOX-SKU-001"
OUT_DIR   = Path(__file__).parent

def make_qr(content: str, filename: str, box_size: int = 12):
    qr = qrcode.QRCode(
        version=2,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=box_size,
        border=4,
    )
    qr.add_data(content)
    qr.make(fit=True)
    img  = qr.make_image(fill_color="black", back_color="white")
    path = OUT_DIR / filename
    img.save(path)
    print(f"Saved: {path}  (content: '{content}')")

if __name__ == "__main__":
    make_qr(SHELF_ID, "shelf_qr.png")
    make_qr(BOX_SKU,  "box_qr.png")
    print("\nNow run the pipeline:")
    print(f'  python amr_vision/vision_main.py --shelf "{SHELF_ID}" --sku "{BOX_SKU}" --dry-run')
