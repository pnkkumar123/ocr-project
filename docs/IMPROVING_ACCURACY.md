# Reducing "Needs Review" & Building Trust

How to take the door detector from *"finds doors but unsure"* to *"an inspector
trusts the output with money on the line."*

## The problem, precisely
On the real LA City set: **63 doors detected, 26 high-confidence, 37 needs-review.**
This is **not** a broken model — localization is accurate (boxes sit on the
door-swing arcs). It's a **domain gap**: the model learned the Roboflow
`doorplan` drawing style, and every architecture firm draws doors slightly
differently (line weight, swing radius, symbol convention). The model recognizes
the *shape* but isn't *confident* on unfamiliar styles, so scores land in the
0.25–0.50 band we flag for review.

Two levers close this: make the model **more confident on your data**
(fine-tuning, tiling, bigger model) and make each detection **verifiable by more
than one signal** (page filtering, cross-confirmation). Reliability = confidence
× traceability.

---

## 1. Fine-tune on real plans — the biggest lever
**Impact: ★★★★★ · Effort: medium · Needs: labeling + one Colab run**

Fine-tuning continues training your existing `door_yolo11.pt` on examples from
the *actual* drawing styles you'll process. This is transfer learning: the model
already knows "door swing arc" generically; you're teaching it *this* firm's
dialect. Because it starts from trained weights (not scratch), it converges fast
and needs far less data than the original training.

**Why it's the real fix:** the review rate is a confidence problem, and nothing
raises confidence on your domain like showing the model your domain. Detections
that currently score 0.35 on an unfamiliar style routinely jump to 0.80+ after a
few hundred in-domain examples.

**How much data:** ~200–300 labeled door instances across 2–3 real sets is a
strong first pass (a handful of floor-plan pages, since each page has 10–30
doors). Diversity of *style* matters more than raw count.

**Workflow:**
1. Render floor-plan pages from real PDFs (the backend already does this →
   `storage/pages/<doc>/*.png`).
2. Upload to a **Roboflow** project → draw boxes on door swings (or import the
   model's current predictions as pre-labels and just *correct* them — much
   faster; this is "model-assisted labeling").
3. Export `YOLOv11`, then in the Colab notebook fine-tune:
   ```python
   model = YOLO('door_yolo11.pt')      # start from YOUR weights, not yolo11n.pt
   model.train(data=REAL_DATA_YAML, epochs=40, imgsz=1024, lr0=0.001, freeze=10)
   ```
   `freeze=10` keeps the early feature layers, `lr0=0.001` (lower) avoids
   wrecking what it already knows.
4. Download `best.pt` → replace `backend/models/door_yolo11.pt`.

**Bonus — feeds component #2:** the cropped door boxes you label here are exactly
the raw material for the door-type classifier (single/double/fire). One labeling
effort, two models.

**Trade-off:** requires manual labeling time. Model-assisted labeling (correcting
predictions instead of drawing from scratch) cuts this by ~3–5×.

---

## 2. Tiled inference / SAHI — big quick win, no training
**Impact: ★★★★☆ · Effort: low · Needs: code only (no retraining)**

Architectural sheets are large (2200px+) and a single door is tiny relative to
the whole sheet. When YOLO resizes the full page down to its input size
(e.g. 1024px), each door shrinks to a few pixels — detail the model needs is
destroyed, so confidence drops.

**SAHI (Slicing Aided Hyper Inference)** fixes this without touching the model:
slice the page into overlapping tiles, run detection on each tile at full
resolution (doors are now "large" within a tile), then merge the boxes back to
page coordinates and de-duplicate overlaps with NMS.

**Why it works:** it's a resolution problem, not a knowledge problem. Give the
same model bigger-looking doors and its existing confidence rises — often lifting
a chunk of the 0.25–0.50 band above 0.50.

**Implementation options:**
- The `sahi` library wraps Ultralytics directly (`AutoDetectionModel` +
  `get_sliced_prediction`).
- Or roll our own: slice with overlap (~20%), run `detector.detect` per tile,
  offset boxes, merge with `torchvision.ops.nms`. Keeps deps light.

**Tuning:** tile size ~640–1024 with 20% overlap is a sensible start. Smaller
tiles = better on tiny doors but slower and more edge-duplicate merging.

**Trade-off:** slower inference (N tiles per page instead of 1). Fine for a
review workflow; for scale, only tile the floor-plan pages (see #4).

---

## 3. Bigger model — yolo11s / yolo11m
**Impact: ★★★☆☆ · Effort: low · Needs: one Colab retrain**

You trained `yolo11n` (nano, 2.6M params) — the smallest, fastest, least
accurate variant. Stepping up gives more capacity to separate doors from
lookalikes (windows, cabinet swings, arcs):

| Model | Params | Relative accuracy | CPU inference |
|---|---|---|---|
| yolo11n | 2.6M | baseline | fastest |
| yolo11s | 9.4M | +several mAP points | still fine |
| yolo11m | 20M | best of the three | slower, OK for review |

Since inference is CPU and this is a review tool (not real-time), `yolo11s` or
`yolo11m` is affordable and a free accuracy bump. **Best combined with #1** —
fine-tune a `yolo11s` on real plans for the strongest single model.

**Trade-off:** larger weights, slower inference. Negligible for a
human-in-the-loop product.

---

## 4. Only detect on floor-plan pages
**Impact: ★★★☆☆ (precision/speed) · Effort: low · Needs: small filter**

A drawing set is mostly *not* floor plans — schedules, details, notes,
elevations. Running detection on those pages wastes time and invents false
positives (a detail drawing of a door, a title-block symbol). We already
classify pages during ingest (`PageInfo.kind`, `has_text_layer`, drawing
counts), so we can **skip non-plan pages** before detection.

**Signals for "this is a floor plan":** high vector-drawing count, moderate text,
landscape aspect, and — pragmatically — pages where the detector finds many doors
cluster together. A simple heuristic (drawings > threshold AND not a
text-dominant schedule page) removes most noise pages.

**Why it builds trust:** fewer spurious detections on irrelevant pages means the
inventory the client sees is cleaner, and every flagged door is on a real plan.

**Trade-off:** risk of skipping an unusual plan page — keep the threshold
conservative and always allow manual "detect this page anyway."

---

## 5. Multi-signal confirmation — the real trust-builder
**Impact: ★★★★★ (trust) · Effort: medium · Needs: schedule parser + OCR wired**

This is what separates a "cool detector" from something an inspection company
puts their name on. A single model's confidence is *one* opinion. Trust comes
from **independent signals agreeing**:

```
Signal A: YOLO detected a door swing here (conf 0.62)
Signal B: An OCR'd door tag "101A" sits inside/next to that box
Signal C: Schedule row 101A exists and says "45 MIN"
  => "Door 101A — fire-rated (45 min), CONFIRMED by detection + tag + schedule"
```

A door backed by 2–3 signals is trustworthy even at moderate detection
confidence, because the *drawing itself* corroborates it. Conversely, a
high-confidence box with **no** nearby tag and **no** schedule row is worth
flagging — maybe it's a cabinet arc, not a door.

**What this needs (later phases, already scaffolded):**
- `schedule_parser` reads the door schedule → rows keyed by tag
  (text-layer path works on 23/41 lacity pages today, no OCR).
- `ocr` reads door tags near detections.
- `cross_reference.associate_tags` + `resolve_fire_rating` join them
  (already implemented as rules).

**Output for the user:** each door shows its **evidence trail** ("detected +
tagged + in schedule"), not just a number. Traceability is the product.

**Trade-off:** depends on the schedule parser and OCR being in place — but the
payoff is the feature that actually closes fire-door inspection sales.

---

## Regional note — UK vs US fire ratings
Fire-rating vocabulary differs and the parser/confirmation logic must handle both:
- **US:** `20 MIN`, `45 MIN`, `60 MIN`, `90 MIN`, `3 HR` (also written `20 MINUTE`).
- **UK:** `FD30`, `FD60`, `FD90`, `FD120`, sometimes `FD30S` (S = smoke seals).
  `FD30` = 30-minute fire door. These appear on UK council-portal drawings and
  will not match US tokens — add them to `_FIRE_RATING_TOKENS`.

---

## Recommended order
1. **#2 Tiled inference** — immediate confidence lift on current weights, no
   retraining, pure code. Ship it first.
2. **#1 Fine-tune on real plans** — the durable fix that closes the domain gap;
   also produces door-type training crops.
3. **#5 Multi-signal confirmation** — pairs with the schedule parser to deliver
   the traceability that builds real trust.
4. **#4 Page filtering** and **#3 bigger model** — low-effort refinements to fold
   in along the way.

## Measuring progress (so "trust" isn't a vibe)
Track these on a fixed set of real pages before/after each change:
- **Review rate** = needs_review / total_doors (today: 37/63 ≈ 59%). Target < 20%.
- **Precision on floor-plan pages** — of flagged doors, how many are real
  (spot-check against the drawing).
- **Schedule-confirmed rate** — % of detected doors that match a schedule tag.
- **Recall** — doors on the plan the system missed (the number that matters most
  for a *safety* product; a missed fire door is the worst failure).

Report these numbers to the client instead of a single accuracy claim — honest,
measurable reliability is more persuasive than "it's 95% accurate."
