# Fine-Tuning the Door Detector on Real Plans

The durable fix for the review rate. Your detector already *finds* doors
(trained on Roboflow `doorplan`); fine-tuning on **real construction plans**
teaches it *your* drawing styles so it's *confident* — turning amber → green and
pushing the review rate toward < 20%. See [IMPROVING_ACCURACY.md](IMPROVING_ACCURACY.md) §1.

This is transfer learning: we continue training the existing `door_yolo11.pt`,
so it converges fast and needs far less data than training from scratch.

---

## 0. The plan at a glance
1. **Collect** 15–40 real floor-plan pages across varied drawing styles.
2. **Render** them to images (the backend already does this).
3. **Pre-label** with the current model (model-assisted labeling) → correct in
   Roboflow instead of drawing from scratch (3–5× faster).
4. **Export** YOLOv11 format.
5. **Fine-tune** from `door_yolo11.pt` on Colab (freeze early layers, low LR).
6. **Evaluate** on a held-out set of real pages; compare review rate.
7. **Iterate** — add the pages it still struggles on (active learning).

Target: **~200–400 labeled door instances** for a strong first pass. Diversity of
*style* matters more than raw count.

---

## 1. Where to download real plans

### 🇬🇧 UK — council planning portals (best source, fully public)
Every UK planning application is public **with drawings attached** — floor plans,
elevations, door schedules. This is the fastest way to get *varied* real styles.
- Search **"[council] public access planning"** → search applications →
  **Documents** tab → download "Proposed Floor Plan" / "General Arrangement" PDFs.
- Portals: Camden, Westminster, Manchester, Birmingham, Leeds, Bristol, Glasgow.
- National: [Planning Portal](https://www.planningportal.co.uk).
- UK fire doors are labelled **`FD30`/`FD60`** — good for testing the parser too.

### 🇺🇸 US — municipal permit portals & bids
- **LA City Planning** document server (our `lacity` source).
- **Seattle DCI / Services Portal**, **SF DBI**, **NYC DOB**, **Denver/Portland**
  permit portals — many publish approved plan sets.
- **University "Capital Projects / Bids"** (.edu) — full sets during bidding.
- **SAM.gov**, **WBDG** (VA sample sets).

### Search recipes that actually return drawing sets
```
"door schedule" "fire rating" floor plan filetype:pdf
"proposed floor plan" filetype:pdf site:gov.uk
arch full set filetype:pdf door schedule
site:.edu bids "door schedule" filetype:pdf
```

### Already in the repo (`datasets/pdfs/`)
- `lacity_door_window_schedule.pdf` (41pp, US, fire ratings)
- `hyperfine_plan_set.pdf` (16pp, residential)
- `lumberone_arch_full_set.pdf` (4pp, US, 20-min doors)

> **Diversity checklist** — aim to cover: residential + commercial; US + UK;
> vector CAD + scanned raster; different firms/line-weights; single/double/sliding
> doors. A model that sees variety generalizes; 40 pages from one firm doesn't.

> **Licensing note:** public planning/permit records are fine for training a
> private model. Don't redistribute the source PDFs themselves; keep them in the
> gitignored `datasets/` folder.

---

## 2. Render pages to label
The backend already renders every page to PNG on ingest
(`storage/pages/<doc>/*.png`). To build a labeling set:
1. Ingest each PDF (`POST /api/documents` or `scripts/test_detection.py`).
2. Grab the **floor-plan pages** only (skip schedules/details) — the pages where
   detection found clusters of doors are your candidates.
3. Copy those PNGs into a `datasets/label_inbox/` folder.

Label at the **same resolution you'll infer at** (render DPI 200 → ~1650×1275+).
Consistent scale = consistent boxes.

---

## 3. Labeling — model-assisted (the time-saver)

**Don't draw every box from scratch.** Use the current model to pre-label, then
just *correct* it. This is 3–5× faster and improves as the model improves.

### Option A — Roboflow "Label Assist" (recommended)
1. Create a free **Roboflow** project → **Object Detection**.
2. Upload your floor-plan PNGs.
3. Upload your `door_yolo11.pt` as a **custom model** (Roboflow supports uploading
   YOLO weights) → enable **Label Assist** → it pre-draws door boxes.
4. Go through each image: **delete false boxes, add missed doors, tighten boxes.**
5. That's the whole job — correcting, not drawing.

### Option B — pre-label locally, import to Roboflow
Generate YOLO label `.txt` files with the current detector, then upload
images+labels to Roboflow and correct. A helper script pattern:
```python
# for each PNG: run DoorDetector, write YOLO-format lines:
# <class> <cx> <cy> <w> <h>   (all normalized 0..1)
```
(We can add `scripts/prelabel.py` for this when you're ready.)

### What to box — labeling conventions (be consistent!)
Consistency matters more than perfection. Decide once and stick to it:
- **Box the door opening: the swing arc + the door leaf line together**, as one
  tight box around the whole door symbol. This matches how `doorplan` was labeled
  and what the model already expects.
- **Include:** hinged/swing doors, double doors (one box for the pair *or* one per
  leaf — pick one rule), sliding/pocket doors, exterior doors.
- **Exclude:** windows, cabinet/closet millwork arcs that aren't doors, door
  symbols in the *legend* or *details* (label only real plan doors), schedule tags.
- **Occluded/faint doors:** still box them — teaching recall on hard cases is the
  point.
- **Edge cases:** if unsure it's a door, check the door schedule/tag nearby.

### Class strategy
- **Phase 1 (now): single class `door`.** Simplest, directly improves detection
  confidence. Start here.
- **Phase 2 (bootstrap component #2): sub-type classes** `single` / `double` /
  `fire`. You can either add these as classes now (more labeling effort) or
  crop the boxes later and train the separate classifier. **Recommended: label
  single-class `door` first**, ship the detection win, then derive door-type
  crops from these same labels — one labeling effort, two models.

### How much to label
- **First pass:** 15–25 pages, ~200–300 door instances. Enough to measurably move
  the review rate.
- **Hold out** 20% of pages as a **validation set the model never trains on** —
  this is how you honestly measure improvement.

---

## 4. Dataset prep & export
In Roboflow:
1. **Split** train/valid/test ≈ 70/20/10 (Roboflow does this automatically).
2. **Preprocessing:** Auto-Orient, and resize to your inference size (e.g. 1024)
   — but since we tile at inference, keeping native/large is fine too.
3. **Augmentation (train only):** modest — slight rotation (±5°), brightness,
   blur. Blueprints are clean line art, so **avoid heavy color/hue augmentation**;
   grayscale/CLAHE-style is more realistic than color jitter.
4. **Export → YOLOv11** → copy the `rf.workspace(...).project(...).version(N)`
   snippet.

---

## 5. Fine-tune on Colab

Add a cell to `colab/train_fire_door_models.ipynb` (or reuse Section 1) — the key
difference is **start from your weights, not `yolo11n.pt`**, freeze early layers,
and use a **lower learning rate** so you refine rather than overwrite:

```python
from ultralytics import YOLO

# download YOUR real-plan dataset (Roboflow snippet)
ds = rf.workspace("WS").project("real-door-plans").version(1).download("yolov11")

model = YOLO("door_yolo11.pt")          # <-- start from trained weights, NOT yolo11n.pt
model.train(
    data = ds.location + "/data.yaml",
    epochs = 40,
    imgsz = 1024,
    lr0 = 0.001,          # low LR: refine, don't wreck existing knowledge
    freeze = 10,          # freeze early feature layers (keep generic door features)
    patience = 15,        # early-stop if val stops improving
    mosaic = 0.5,         # lighter mosaic aug for line-art
    project = "runs", name = "door_finetune",
)
print("best:", model.trainer.best)      # copy to backend/models/door_yolo11.pt
```

**Why these settings:**
- `door_yolo11.pt` start → keeps everything it already learned; you're *adding*
  your domain, not restarting.
- `freeze=10` → early layers detect generic edges/arcs (already good); we mainly
  retrain the head on your styles. Prevents overfitting on a small set.
- `lr0=0.001` (10× lower than the 0.01 from-scratch default) → small, careful
  updates.
- `patience=15` → stop when validation plateaus, avoid overfitting.

Optionally step the backbone up to **`yolo11s`** here for more accuracy (retrain
from `yolo11s.pt` on `doorplan` + real data combined). Still fine on CPU inference.

---

## 6. Evaluate — prove it improved
Don't trust vibes; measure on the **held-out real pages**:
```python
metrics = model.val()
print("door mAP50:", metrics.box.map50, "| mAP50-95:", metrics.box.map)
```
Then re-run backend detection on a fixed set of real pages and compare the
**review rate** before vs after (baseline today: 38% tiled, 59% whole-page):

| Checkpoint | door mAP50 | Review rate (real pages) |
|---|---|---|
| Base (`doorplan` only) | 0.944 (on doorplan val) | 38% tiled |
| + Real-plan fine-tune | *measure* | *target < 20%* |

Also track **recall** (missed doors) — for a safety product, a missed fire door
is the worst error, so watch that it stays high.

---

## 7. Iterate — active learning loop
The efficient way to keep improving with minimal labeling:
1. Run the new model on **fresh** real plans.
2. Find pages where it's **still unsure** (many amber boxes) or **wrong**.
3. Label *those* pages (the hard cases teach the most) → add to the dataset.
4. Re-fine-tune. Repeat.

Each loop targets exactly the model's weak spots, so labeling effort keeps paying
off instead of re-teaching what it already knows.

---

## 8. Pitfalls to avoid
- **Inconsistent boxes** — the #1 killer. Box the same thing the same way every
  time. Write your convention at the top of the Roboflow project.
- **Training from `yolo11n.pt` instead of your weights** — throws away the
  `doorplan` learning. Always fine-tune *from* `door_yolo11.pt`.
- **Over-augmenting** line art with color/hue — unrealistic; hurts more than helps.
- **No held-out set** — you can't claim improvement without validation pages the
  model never saw.
- **Labeling legend/detail doors** — only label real doors on the actual plan.
- **One-firm dataset** — looks great on that firm, fails on the next. Diversify.

---

## 9. Deliverable path
1. Collect + label ~20 real pages (model-assisted) → export.
2. Fine-tune from `door_yolo11.pt` on Colab → download `best.pt`.
3. Replace `backend/models/door_yolo11.pt`.
4. Re-run detection → confirm review rate drop → log it in
   [PROGRESS.md](PROGRESS.md).
5. Reuse the same labels to bootstrap door-type classification (component #2).
