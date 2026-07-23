# Model weights

Trained on Google Colab (see `../../colab/`), used here for **inference**.

Drop the downloaded `.pt` files here:

| File | Component | Loaded by |
|---|---|---|
| `door_yolo11.pt` | #1 door detection | `app/pipeline/door_detector.py` |
| `door_type.pt` | #2 door-type classify | (Phase 3 wiring) |
| `wall_seg.pt` | #5 wall-rating segmentation | `app/pipeline/wall_rating.py` |

`.pt` files are gitignored (large). Keep them in cloud storage / Colab and
re-download as needed.
