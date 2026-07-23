"""Component #1 — YOLOv11 door symbol detection (inference).

Weights trained on Colab (`colab/train_fire_door_models.ipynb`) and dropped in
`backend/models/door_yolo11.pt`. The training dataset had 5 classes
(door, text, stair, compass, scale), so we filter to `door` here and keep the
`text` class available for later tag/label matching (component #3).

Reliability-first: every detection carries a confidence, and anything below
`review_conf` is flagged `needs_review` rather than silently trusted/dropped.

Tiled inference (`tile=True`): architectural sheets are large and a door is tiny
relative to the full page, so downscaling to the model input destroys the detail
the model needs (confidence drops). We slice the page into overlapping tiles,
detect per-tile at full resolution, map boxes back to page coordinates, and
de-duplicate overlaps with NMS. See docs/IMPROVING_ACCURACY.md §2.

Heavy imports (torch/ultralytics) are lazy so the API boots without them.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.models.schemas import BoundingBox, DoorDetection

DEFAULT_WEIGHTS = Path(__file__).resolve().parents[2] / "models" / "door_yolo11.pt"

# One detection = (x1, y1, x2, y2, confidence) in page-pixel coordinates.
_Box = tuple[float, float, float, float, float]


class DoorDetector:
    def __init__(
        self,
        weights: str | Path = DEFAULT_WEIGHTS,
        conf: float = 0.25,          # min confidence to report at all
        review_conf: float = 0.50,   # below this -> flagged for human review
        target_classes: tuple[str, ...] = ("door",),
        tile: bool = True,           # tiled inference for large pages
        tile_size: int = 1024,
        overlap: float = 0.2,        # 20% tile overlap so edge doors aren't cut
        nms_iou: float = 0.5,        # merge threshold for overlapping tile boxes
    ) -> None:
        self.weights = Path(weights)
        self.conf = conf
        self.review_conf = review_conf
        self.target_classes = target_classes
        self.tile = tile
        self.tile_size = tile_size
        self.overlap = overlap
        self.nms_iou = nms_iou
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            if not self.weights.exists():
                raise FileNotFoundError(
                    f"Door weights not found at {self.weights}. Train on Colab and "
                    f"drop door_yolo11.pt into backend/models/."
                )
            from ultralytics import YOLO  # lazy heavy import

            self._model = YOLO(str(self.weights))
        return self._model

    def _run(self, image) -> list[_Box]:
        """Run the model on a single PIL image; return target-class boxes."""
        return self._run_batch([image])[0]

    def _run_batch(self, images: list) -> list[list[_Box]]:
        """Run the model over several images in one forward pass instead of one
        Python-level call per tile — same detections (batching doesn't change
        model output), just less per-call overhead. A large sheet tiles into a
        dozen+ crops, so this is a real win at zero accuracy cost."""
        model = self._ensure_model()
        names = model.names
        out: list[list[_Box]] = []
        for r in model(images, conf=self.conf, verbose=False):
            boxes: list[_Box] = []
            for box in r.boxes:
                if names[int(box.cls[0])] not in self.target_classes:
                    continue
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                boxes.append((x1, y1, x2, y2, float(box.conf[0])))
            out.append(boxes)
        return out

    def _tile_boxes(self, image_path: str) -> list[_Box]:
        """Slice into overlapping tiles, detect all tiles in one batched pass,
        offset boxes back to page coordinates."""
        with Image.open(image_path) as im:
            W, H = im.size
            if max(W, H) <= self.tile_size:
                return self._run(im.convert("RGB"))

            step = max(1, int(self.tile_size * (1 - self.overlap)))
            img = im.convert("RGB")
            tiles: list = []
            offsets: list[tuple[int, int]] = []
            for top in range(0, H, step):
                for left in range(0, W, step):
                    right, bottom = min(left + self.tile_size, W), min(top + self.tile_size, H)
                    tiles.append(img.crop((left, top, right, bottom)))
                    offsets.append((left, top))
                    if right >= W:
                        break
                if bottom >= H:
                    break

        all_boxes: list[_Box] = []
        for (left, top), boxes in zip(offsets, self._run_batch(tiles)):
            for x1, y1, x2, y2, c in boxes:
                all_boxes.append((x1 + left, y1 + top, x2 + left, y2 + top, c))
        return self._nms(all_boxes)

    def _nms(self, boxes: list[_Box]) -> list[_Box]:
        """De-duplicate overlapping detections from adjacent tiles."""
        if len(boxes) <= 1:
            return boxes
        import torch
        from torchvision.ops import nms

        t = torch.tensor([[b[0], b[1], b[2], b[3]] for b in boxes], dtype=torch.float32)
        scores = torch.tensor([b[4] for b in boxes], dtype=torch.float32)
        keep = nms(t, scores, self.nms_iou).tolist()
        return [boxes[i] for i in keep]

    def detect(self, image_path: str, page_index: int) -> list[DoorDetection]:
        raw = self._tile_boxes(image_path) if self.tile else self._run(
            Image.open(image_path).convert("RGB")
        )
        detections: list[DoorDetection] = []
        for x1, y1, x2, y2, confidence in raw:
            detections.append(
                DoorDetection(
                    page_index=page_index,
                    box=BoundingBox(x=x1, y=y1, w=x2 - x1, h=y2 - y1),
                    confidence=confidence,
                    door_type="unknown",  # single/double/fire -> component #2 later
                    needs_review=confidence < self.review_conf,
                )
            )
        return detections
