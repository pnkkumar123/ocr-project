# Colab Training

Train the 3 trainable models on Colab's free GPU, then use the weights in the
backend for **inference** (no GPU needed locally).

## Workflow
1. Upload `train_fire_door_models.ipynb` to [Google Colab](https://colab.research.google.com)
   (File → Upload notebook).
2. **Runtime → Change runtime type → GPU (T4)**.
3. Run Section 0 (install/setup).
4. **Section 1, cell 6:** paste your Roboflow key into
   `ROBOFLOW_API_KEY = '...'`, and paste the dataset's exact
   `workspace/project/version` from its **Download Dataset → YOLOv11** dialog.
5. Run cells top to bottom.
6. Section 4 downloads `fire_door_weights.zip` → unzip into `backend/models/`.

> **Security:** the API key goes only into the live Colab session — never commit
> it to git. If it leaks into a file, rotate it at roboflow.com → Settings → API.

## Models produced
| Section | Weight | Backend loader |
|---|---|---|
| 1 Door detection | `door_yolo11.pt` | `app/pipeline/door_detector.py` |
| 2 Door-type classify | `door_type.pt` | (wire in Phase 3) |
| 3 Wall-rating seg | `wall_seg.pt` | `app/pipeline/wall_rating.py` |

## Data notes
- **Doors (1):** default pulls a public Roboflow door dataset — trains immediately.
  Swap `WORKSPACE/PROJECT/VERSION` for your own labeled construction-plan set later.
- **Door-type (2):** needs a folder-per-class image set (`single/double/fire`).
  Easiest: crop door boxes from Section 1 predictions into class folders.
- **Wall-seg (3):** needs an instance-segmentation dataset you label yourself
  (Roboflow → Instance Segmentation → export `yolov11`). Scaffold until then.

## Using the weights locally (inference only)
```bash
cd backend
py -3.12 -m venv .venv-ml          # already created
./.venv-ml/Scripts/python.exe -m pip install -r requirements-ml.txt
# drop the .pt files into backend/models/, then the pipeline loads them
```
Local inference is CPU (no GPU) — fine for a demo. Retrain on Colab whenever you
add data.
