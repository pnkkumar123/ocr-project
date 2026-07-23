# AWS Resources & Cost Optimization

A well-researched sizing + cost plan for running the fire-door detection system
on AWS. Pricing is `us-east-1`, verified against AWS 2026 rates (sources at
bottom). Treat dollar figures as planning estimates, not quotes.

## TL;DR
- **Inference is CPU-only** (YOLOv11n + PDF render + OCR). **No GPU needed to
  serve.** GPU is only for occasional fine-tuning — and that stays on Colab/Spot,
  not a 24/7 AWS GPU.
- The workload is **bursty and short** (a 40-page set ≈ 1–4 min of compute), so
  the enemy is **idle cost**, not compute. Architect for **scale-to-zero**.
- **Per-document compute is tiny** (~$0.002–0.01). Cost is dominated by (a) idle
  always-on services and (b) **OCR strategy** (managed Textract vs self-hosted).
- The **vector text-layer path is a massive cost lever**: pages with a text layer
  (23/41 on our real set) need **no OCR at all** → parse text directly = free.

---

## 1. Workload profile (what actually runs)
| Stage | Resource | Rough cost driver |
|---|---|---|
| PDF render (PyMuPDF) | CPU, ~0.2–0.5 s/page | short |
| Door detection (YOLOv11n) | CPU, ~0.1–0.3 s/page (×N tiles if tiled) | short–medium |
| OCR tags/schedule (only where no text layer) | CPU or Textract | **main variable cost** |
| Table structure (schedule pages only) | CPU or Textract | few pages/set |
| Cross-reference + export | CPU, negligible | trivial |

**Memory** is driven by the ML models held in RAM: torch + YOLO ≈ 1.5–2 GB;
add OCR/table models ≈ +1–2 GB. A worker of **2 vCPU / 8 GB** comfortably runs
the full pipeline. Processing a 40-page set end-to-end on CPU ≈ **1–4 minutes**.

---

## 2. Reference architecture (evolves with scale)

```
        Next.js (Vercel/S3+CloudFront)
                    │ HTTPS
                    ▼
        API  ── writes PDF ──▶  S3 (uploads/)
      (Lambda or       │ enqueue job
       Fargate)        ▼
                     SQS queue
                        │ triggers
                        ▼
              Worker (scale-to-zero)
        ┌───────────────────────────────┐
        │ render → YOLO → OCR → schedule │
        │ → cross-ref → annotate/export  │
        └───────────────────────────────┘
             │ results            │ artifacts
             ▼                    ▼
        RDS/DynamoDB          S3 (outputs/)
             ▲                    │
             └── API reads ◀──────┘  (annotated PNGs, Excel via CloudFront)
```

**Why async + SQS:** processing takes minutes; you don't hold an HTTP connection
open. The API returns a `job_id` immediately; the worker runs when there's work
and **scales to zero when the queue is empty** — you pay nothing while idle.

---

## 3. Compute sizing & options

| Component | MVP choice | Scale choice | Notes |
|---|---|---|---|
| API | Lambda (container) + API Gateway | ECS Fargate 0.5 vCPU/1 GB ×2 | Lambda = ~$0 idle |
| Worker | Lambda container (10 GB image, 15-min cap) | ECS Fargate 2 vCPU/8 GB, Spot, min=0 | scale-to-zero both |
| Queue | SQS | SQS | ~$0 at low volume |
| Metadata DB | DynamoDB on-demand | RDS Postgres (t4g) | Dynamo = pay-per-request |
| Files | S3 Standard + lifecycle | S3 + Intelligent-Tiering | see §6 |
| Frontend | S3 + CloudFront (or Vercel) | same | static, cheap |

**Fargate rate (2026):** $0.04048 / vCPU-hr + $0.004445 / GB-hr. A **2 vCPU / 8 GB**
worker = **$0.1165/hr** on-demand → a 3-min job ≈ **$0.006** (Spot ≈ $0.002).
**Use Graviton (ARM)** Fargate/Lambda where possible: ~20% cheaper and better
price/performance; torch-CPU + ultralytics run fine on ARM.

---

## 4. The OCR decision — biggest cost fork

**Amazon Textract (managed, zero infra):**
- Raw text: **$1.50 / 1,000 pages**. Tables **$15 / 1,000 pages**. Forms $15/1,000.
- Great for MVP (no servers, high accuracy), but **expensive at scale** — a schedule
  table page costs $0.015, and volume adds up fast.

**Self-hosted (PaddleOCR / EasyOCR + Table Transformer on the CPU worker):**
- Near-zero marginal cost (just more worker seconds), but you own the infra and it
  uses more RAM/CPU.

**The optimization that beats both:** our page classifier already flags
`has_text_layer`. **Text-layer pages need no OCR** — read the schedule straight
from the PDF text (exact + free). On the real LA City set that's **23/41 pages**.
So only *true raster* pages ever hit OCR. This can cut OCR volume by 50–90%.

**Rule of thumb:** Textract for MVP/low volume → migrate to self-hosted OCR once
monthly table-page volume × $0.015 exceeds a small Fargate worker (~a few
thousand table-pages/month is the crossover).

---

## 5. Cost scenarios (itemized, monthly)

Assumptions: avg 30-page set; ~20% of pages need OCR after the text-layer filter.

### A. MVP / pilot — ~500 docs/mo (~15k pages)
| Item | Est. |
|---|---|
| API + worker (Lambda, scale-to-zero, ~17 compute-hrs) | $2–8 |
| Textract (OCR + tables on ~3k pages) | $30–45 |
| S3 + DynamoDB + SQS + transfer | $5–15 |
| **Total** | **≈ $40–70/mo** |

Scale-to-zero + Textract = you pay almost only for actual work. Ideal to start.

### B. Small SaaS — ~10,000 docs/mo (~300k pages)
| Item | Self-hosted OCR | Textract OCR |
|---|---|---|
| Worker compute (Fargate Spot) | $15–80 | $15–40 |
| API (Fargate ×2, HA) | $36 | $36 |
| OCR/tables | *in worker* ~$0 | **$300–900** |
| S3 (lifecycle) + DB + queue + transfer | $30–80 | $30–80 |
| **Total** | **≈ $120–250/mo** | **≈ $400–1,050/mo** |

**At this volume, self-hosting OCR is the clear win** — Textract's per-page table
cost dominates. The text-layer filter keeps either path lower.

### C. Growth — ~100,000 docs/mo (~3M pages)
| Item | Est. (self-hosted, Spot, Graviton) |
|---|---|
| Worker compute (Spot Fargate/EC2) | $120–400 |
| API (autoscaled) | $70–150 |
| S3 (Intelligent-Tiering + lifecycle) | $50–150 |
| DB (RDS t4g) + queue + transfer + monitoring | $80–250 |
| **Total** | **≈ $350–950/mo** |

Textract at this scale would add **$3,000+/mo** for tables alone — avoid;
self-host OCR.

---

## 6. Cost-optimization levers (ranked)
1. **Scale-to-zero workers** — SQS + Fargate `min=0` (or Lambda). Pay per job,
   nothing while idle. Biggest single saver for bursty load.
2. **Text-layer-first (skip OCR)** — parse the schedule from the PDF text layer;
   only OCR true raster pages. Cuts the dominant variable cost 50–90%.
3. **Spot capacity** — Fargate Spot / EC2 Spot for workers: up to **70–90% off**.
   Safe because jobs are idempotent and re-queueable on interruption.
4. **Graviton (ARM)** — ~20% cheaper compute, better price/perf; models run on ARM.
5. **Self-host OCR past the crossover** — replace Textract with PaddleOCR/TATR on
   the worker once table-page volume makes Textract pricier than a small task.
6. **Only detect floor-plan pages** — skip schedule/detail sheets (we already
   classify pages) → less compute and fewer false positives.
7. **S3 lifecycle** — expire or Glacier-tier rendered PNGs after N days (they're
   regenerable from the source PDF); keep only source PDFs + final outputs hot.
   Use Intelligent-Tiering for unpredictable access.
8. **Right-size memory** — OCR models set the RAM floor; load lazily and only on
   pages that need them so most tasks run leaner.
9. **Slim container image** — `torch` **CPU** wheel (not CUDA, ~10× smaller),
   multi-stage build, ECR. Faster cold starts, lower storage.
10. **Compute Savings Plans / Reserved** — once you have a steady always-on
    baseline (API), commit for up to ~50% off that portion.
11. **Cache & dedupe** — hash uploads; if the same PDF is reprocessed, return the
    stored result instead of recomputing.
12. **Batch off-peak** — for non-urgent bulk sets, drain the queue on Spot during
    cheap windows.

---

## 7. GPU: only for training, never for serving
- **Serving:** YOLOv11n + OCR run fine on CPU (verified locally). A 24/7 AWS GPU
  (`g4dn.xlarge` ≈ $0.526/hr ≈ **$380/mo**, `g5.xlarge` ≈ $1.006/hr ≈ $725/mo)
  would be wasted money here.
- **Fine-tuning:** keep it on **Colab** (free/Pro) or, if you outgrow that, a
  **Spot** `g4dn.xlarge` (~$0.16–0.21/hr) spun up only for the training run, or
  **SageMaker Training** (managed, pay per job). Never keep a GPU idle.

---

## 8. Recommended infra path (matches the build phases)
1. **MVP:** Lambda (container) API + worker, SQS, S3, DynamoDB, **Textract** for
   OCR. Scale-to-zero → ~$40–70/mo. Zero ops, ship fast.
2. **Pilot → SaaS:** move the worker to **ECS Fargate Spot (Graviton, min=0)**,
   switch OCR to **self-hosted** once volume crosses the Textract line, add RDS.
3. **Scale:** Spot everywhere, Intelligent-Tiering, Savings Plan on the API
   baseline, caching/dedupe, page-filtering. Keeps a 100k-docs/mo build under
   ~$1k/mo.

## 9. What drives the bill (so you can defend it to a client)
- **Not** the AI compute — that's cents per document.
- **Idle always-on services** → fixed by scale-to-zero.
- **OCR page volume** → fixed by the text-layer filter + self-hosting at scale.
- **Storage of rendered images** → fixed by S3 lifecycle (regenerate on demand).

---

### Sources (AWS pricing, 2026)
- [AWS Fargate Pricing](https://aws.amazon.com/fargate/pricing/) — $0.04048/vCPU-hr, $0.004445/GB-hr; Spot up to 70% off.
- [Amazon Textract Pricing](https://aws.amazon.com/textract/pricing/) — $1.50/1k pages text; $15/1k pages tables/forms.
- [EC2 Spot Pricing](https://aws.amazon.com/ec2/spot/pricing/) — up to 90% off on-demand.
- g4dn.xlarge ≈ $0.526/hr, g5.xlarge ≈ $1.006/hr on-demand ([Vantage](https://instances.vantage.sh/aws/ec2/g4dn.xlarge)).
- [Fargate Compute Savings Plans](https://aws.amazon.com/savingsplans/) — up to ~50% off committed baseline.
