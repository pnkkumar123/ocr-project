"""Fire-door detection pipeline.

Stage order:
  1. ingest            -> render pages, classify vector/raster      (DONE)
  2. door_detector     -> YOLOv11 door symbol detection             (#1)
  3. door_classifier   -> single/double/fire door-type classes      (#2)
  4. ocr               -> door tags + schedule text                 (#3)
  5. schedule_parser   -> Table Transformer / PP-Structure          (#4)
  6. wall_rating       -> fire-barrier line segmentation            (#5)
  7. cross_reference   -> tag<->schedule join, fire-rating logic     (rules)
  8. annotate + export -> highlighted PDF, Excel/CSV
"""
