"""
merge_dataset.py
----------------
Merges 3 separate Roboflow YOLOv8 datasets into ONE dataset with 3 classes.

CLASS MAPPING (fixed — do not change, must match training and inference):
    0 = box
    1 = qr
    2 = barcode

HOW TO USE:
    1. Extract your 3 Roboflow ZIPs into the raw/ folders below
    2. Run:  python merge_dataset.py
    3. Output goes to:  datasets/merged/

WHAT THIS SCRIPT DOES:
    - Walks through train/valid/test splits in each source dataset
    - Remaps class IDs in every .txt label file
    - Copies images with a unique prefix (avoids name collisions)
    - Writes new label files with corrected class IDs
    - Generates a final data.yaml ready for Colab training
    - Prints a summary so you can verify nothing was missed
"""

import os
import shutil
import yaml
from pathlib import Path

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

# Max images to take from each source per split (train/valid/test).
# Reason: box dataset has 20k images — using all would create class imbalance
# and make Colab training take 8+ hours (free GPU disconnects at ~12h).
# 3000 per source = ~9000 training images total -> ~1 hour on Colab free tier.
# Set to None to use every image (no cap).
MAX_PER_SOURCE = 3000

BASE_DIR = Path(r"C:\Users\abdal\AMR-Warehouse-System\datasets")

SOURCES = [
    {
        "name":     "box",           # human label — appears in console output
        "path":     BASE_DIR / "raw" / "box_dataset",
        "class_map": {0: 0},         # all classes in this dataset -> new class IDs
        # If your box dataset has multiple classes, add them:
        # "class_map": {0: 0, 1: 0}  means both old-0 and old-1 -> new-0 (box)
    },
    {
        "name":     "qr",
        "path":     BASE_DIR / "raw" / "qr_dataset",
        "class_map": {0: 1},         # old class 0 (qr) -> new class 1
    },
    {
        "name":     "barcode",
        "path":     BASE_DIR / "raw" / "barcode_dataset",
        "class_map": {0: 2},         # old class 0 (barcode) -> new class 2
        # Split override: barcode train labels are missing from this dataset.
        # The test split (562 labeled images) becomes our training data.
        # Format: {source_split: destination_split}
        "split_override": {"test": "train"},
    },
]

OUTPUT_DIR  = BASE_DIR / "merged"

# Final class names in order — index must match class ID above
CLASS_NAMES = ["box", "qr", "barcode"]

# Splits to process — standard Roboflow names
SPLITS = ["train", "valid", "test"]

# ─────────────────────────────────────────────
# MERGE LOGIC — no need to edit below this line
# ─────────────────────────────────────────────

def remap_label_file(src_label_path, dst_label_path, class_map):
    """
    Read a YOLOv8 .txt label file, remap class IDs, write to destination.
    Lines with unknown class IDs are skipped with a warning.
    Format per line: class_id x_center y_center width height
    All values are floats except class_id which is int.
    """
    new_lines = []
    skipped   = 0

    with open(src_label_path, "r") as f:
        lines = f.read().strip().splitlines()

    for line in lines:
        if not line.strip():
            continue  # skip blank lines

        parts = line.split()
        if len(parts) < 5:
            skipped += 1
            continue  # malformed line

        old_cls = int(parts[0])

        if old_cls not in class_map:
            # This class ID is not in our mapping — skip it
            # Example: Roboflow QR dataset may include a "barcode" class
            # we don't want — just omit it
            skipped += 1
            continue

        new_cls   = class_map[old_cls]
        remainder = " ".join(parts[1:])       # x y w h unchanged
        new_lines.append(f"{new_cls} {remainder}")

    with open(dst_label_path, "w") as f:
        f.write("\n".join(new_lines))

    return len(new_lines), skipped


def process_split(source_cfg, src_split, dst_split, out_dir, counters):
    """
    Copy one split from one source dataset into out_dir.
    src_split: the split name in the SOURCE folder (e.g. 'test')
    dst_split: the split name in the OUTPUT folder (e.g. 'train')
    These differ when split_override is used (e.g. barcode test -> merged train).
    Prefixes filenames with the source name to prevent collisions.
    """
    src_images = source_cfg["path"] / src_split / "images"
    src_labels = source_cfg["path"] / src_split / "labels"

    dst_images = out_dir / dst_split / "images"
    dst_labels = out_dir / dst_split / "labels"
    dst_images.mkdir(parents=True, exist_ok=True)
    dst_labels.mkdir(parents=True, exist_ok=True)

    if not src_images.exists():
        print(f"  [SKIP] {source_cfg['name']} / {src_split} -- folder not found")
        return

    prefix    = source_cfg["name"]
    class_map = source_cfg["class_map"]
    copied    = 0
    skipped   = 0

    all_images = [f for f in src_images.iterdir()
                  if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp")]

    # Apply cap: sort for reproducibility, then slice
    if MAX_PER_SOURCE is not None and len(all_images) > MAX_PER_SOURCE:
        all_images = sorted(all_images)[:MAX_PER_SOURCE]

    for img_file in all_images:

        # Unique destination name: prefix_originalname.ext
        dst_img_name = f"{prefix}_{img_file.name}"
        dst_lbl_name = f"{prefix}_{img_file.stem}.txt"

        src_lbl = src_labels / (img_file.stem + ".txt")

        # Skip images that have no label file (unannotated)
        if not src_lbl.exists():
            skipped += 1
            continue

        shutil.copy2(img_file, dst_images / dst_img_name)

        labels_written, lines_skipped = remap_label_file(
            src_lbl,
            dst_labels / dst_lbl_name,
            class_map
        )

        if labels_written == 0:
            # Label file exists but had no valid annotations after remapping
            # Remove the image too — YOLO doesn't like orphan images
            (dst_images / dst_img_name).unlink()
            skipped += 1
        else:
            copied += 1

    counters[dst_split]["copied"]  += copied
    counters[dst_split]["skipped"] += skipped
    tag = f"{src_split}->{dst_split}" if src_split != dst_split else src_split
    print(f"  {tag:12}  ->  {copied:4d} images copied,  {skipped:3d} skipped")


def write_data_yaml(out_dir, class_names):
    """
    Write the data.yaml that Colab (ultralytics) will read during training.
    Paths use forward slashes — works on both Windows and Linux/Jetson.
    """
    yaml_content = {
        "train": "../train/images",
        "val":   "../valid/images",
        "test":  "../test/images",
        "nc":    len(class_names),
        "names": class_names,
    }
    yaml_path = out_dir / "data.yaml"
    with open(yaml_path, "w") as f:
        yaml.dump(yaml_content, f, default_flow_style=False, sort_keys=False)
    print(f"\ndata.yaml written -> {yaml_path}")


def main():
    print("=" * 55)
    print("  AMR Vision — Dataset Merge Script")
    print(f"  Classes: {CLASS_NAMES}")
    print("=" * 55)

    # Verify all source folders exist before starting
    all_ok = True
    for src in SOURCES:
        if not src["path"].exists():
            print(f"[ERROR] Source folder not found: {src['path']}")
            print(f"        Extract your {src['name']} ZIP into that folder first.")
            all_ok = False
    if not all_ok:
        print("\nFix the missing folders and run again.")
        return

    # Clear and recreate output directory
    if OUTPUT_DIR.exists():
        print(f"\nCleaning previous output: {OUTPUT_DIR}")
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True)

    # Counters for final summary
    counters = {s: {"copied": 0, "skipped": 0} for s in SPLITS}

    # Process each source
    for src in SOURCES:
        override = src.get("split_override", {})  # e.g. {"test": "train"}
        print(f"\n[{src['name'].upper()} DATASET]  class_map={src['class_map']}")
        if override:
            print(f"  split_override: {override}")

        # Build the list of (src_split, dst_split) pairs to process.
        # Regular splits: src==dst. Overridden splits: src!=dst.
        # Skip any normal split that is the SOURCE of an override (already remapped).
        overridden_sources = set(override.keys())
        pairs = []
        for split in SPLITS:
            if split not in overridden_sources:
                pairs.append((split, split))
        for src_split, dst_split in override.items():
            pairs.append((src_split, dst_split))

        for src_split, dst_split in pairs:
            process_split(src, src_split, dst_split, OUTPUT_DIR, counters)

    # Write data.yaml
    write_data_yaml(OUTPUT_DIR, CLASS_NAMES)

    # Final summary
    print("\n" + "=" * 55)
    print("  MERGE COMPLETE — Summary")
    print("=" * 55)
    total = 0
    for split in SPLITS:
        c = counters[split]["copied"]
        s = counters[split]["skipped"]
        total += c
        print(f"  {split:6}  {c:5d} images   ({s} skipped)")
    print(f"  {'TOTAL':6}  {total:5d} images")
    print(f"\n  Output: {OUTPUT_DIR}")
    print("\nNext step: zip the 'merged' folder and upload to Google Drive for Colab.")


if __name__ == "__main__":
    main()
