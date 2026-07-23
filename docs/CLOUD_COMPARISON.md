# Cloud Comparison — AWS vs Azure vs GCP

Which of the big three is most **reliable** and **cost-effective** for *this*
project. Pricing is 2026, directional (regions/discounts vary) — sources at
bottom. Companion to [AWS_COST.md](AWS_COST.md).

## TL;DR verdict
- **Reliability is a non-differentiator.** All three offer ~**99.9%+ SLAs** on the
  services we need and run this workload dependably. Don't pick on reliability —
  pick on fit and cost.
- **Best fit for this project (bursty, containerized, scale-to-zero, solo/MVP):
  🥇 GCP Cloud Run.** Cleanest scale-to-zero, simplest deploy (container → URL),
  generous free tier. Lowest friction for one developer shipping an MVP.
- **Cheapest managed document AI: 🥇 Azure AI Document Intelligence** ($10/1k
  pages for tables vs AWS $15–65/1k). Best if you lean on managed OCR or the
  client is a Microsoft/enterprise shop.
- **AWS** is the safe, most-hireable default with the broadest ecosystem, but
  **priciest for managed table OCR** and its scale-to-zero (Fargate/Lambda) is
  less elegant than Cloud Run / Container Apps.
- **Because the app is a plain Docker container, it's portable** across all three
  — so this is a low-lock-in, reversible decision.

---

## 1. What this project actually needs from a cloud
1. **Scale-to-zero container compute** — bursty jobs (1–4 min each), must pay ~$0
   while idle. *The single most important criterion.*
2. **Object storage** — PDFs + rendered images.
3. **Document AI (optional)** — managed OCR/table extraction, or self-host.
4. **A queue** — async job dispatch.
5. **Cheap GPU for occasional fine-tuning** — or keep on Colab.
6. **A small managed DB** — job/results metadata.

## 2. Service equivalents
| Need | AWS | Azure | GCP |
|---|---|---|---|
| Scale-to-zero containers | Fargate (min=0) / Lambda | **Container Apps** | **Cloud Run** |
| Object storage | S3 | Blob Storage | Cloud Storage (GCS) |
| Managed document AI | Textract | **AI Document Intelligence** | Document AI |
| Queue | SQS | Storage Queue / Service Bus | Pub/Sub |
| Managed DB | DynamoDB / RDS | Cosmos DB / Azure SQL | Firestore / Cloud SQL |
| Spot GPU (fine-tune) | EC2 Spot g4dn | Spot VM (NC-series) | Spot VM + GPU |
| Static frontend | S3+CloudFront | Static Web Apps | Firebase Hosting / GCS+CDN |

---

## 3. The core: scale-to-zero container compute
This workload is *made* for scale-to-zero — it's idle most of the time and bursts
when a set is uploaded.

| Platform | Scale-to-zero | Billing | Free tier | DX for this project |
|---|---|---|---|---|
| **GCP Cloud Run** | ✅ native, excellent | per-request + per vCPU/GiB-second | **2M requests/mo free** | ⭐ simplest: `deploy` a container → HTTPS URL |
| **Azure Container Apps** | ✅ native | ~$0.000024/vCPU-s + $0.000003/GiB-s active | monthly free grant | ⭐ strong, KEDA autoscaling, good queue triggers |
| **AWS Fargate** | ⚠️ via ECS `min=0` (less clean) | $0.04048/vCPU-h + $0.004445/GiB-h | none | more moving parts (ECS/ALB/task defs) |
| **AWS Lambda** | ✅ native | per-ms | 1M req/mo free | 15-min cap, 10 GB image — OK for MVP, tight for heavy pages |

**Read:** Cloud Run and Container Apps are *purpose-built* for this pattern and
bill only while a request/job is actually running. Fargate scales to zero only
with extra ECS wiring; Lambda works but its 15-min/10 GB limits chafe on large
tiled pages. **For a bursty document pipeline, Cloud Run is the least-effort,
lowest-idle-cost choice.**

---

## 4. Managed document AI — cost per 1,000 pages
Only relevant if you use managed OCR instead of self-hosting. Table extraction is
the schedule-parsing cost that matters.

| Service | Plain OCR / Read | **Tables / Layout** | Forms+Tables |
|---|---|---|---|
| **Azure AI Document Intelligence** | $1.50 | **$10 (Layout)** ⭐ | — |
| **Google Document AI** | $1.50 (→$0.60 past 5M) | $10–30 | — |
| **AWS Textract** | $1.50 | $15 | **$65** (priciest) |

**Read:** for structured **table** extraction — exactly what a door schedule is —
**Azure is cheapest ($10/1k)**, Google competitive, **AWS most expensive**. At
scale this can be hundreds of $/month of difference. (Reminder from
[AWS_COST.md](AWS_COST.md): the **text-layer path avoids managed OCR entirely** on
~half the pages, shrinking this line whichever vendor you choose.)

---

## 5. Reliability & track record
| | AWS | Azure | GCP |
|---|---|---|---|
| Compute SLA (these services) | ~99.9%+ | ~99.9%+ | ~99.9%+ |
| Global regions | most | many | fewer but strong network |
| Track record | longest, broadest | strong enterprise | strong data/AI + networking |
| Ecosystem / hireability | largest | large (MS shops) | growing |

All three are **production-reliable** for this app. Differences are ecosystem and
familiarity, not uptime. If a client mandates a cloud (common in enterprise —
often Azure), that overrides everything below.

---

## 6. Cost-effectiveness by scenario
Container compute is similar across vendors (cents/job); the differentiators are
**idle handling** (Cloud Run/Container Apps win) and **managed-OCR price** (Azure
cheapest, AWS priciest). Using the [AWS_COST.md](AWS_COST.md) scenarios:

| Scenario | Cheapest-fit stack | Rough $/mo | Why |
|---|---|---|---|
| **MVP (~500 docs)** | **GCP Cloud Run** + GCS + Document AI | **$30–60** | free tier + true scale-to-zero; near-$0 idle |
| **Small SaaS (~10k docs)** — self-host OCR | Cloud Run **or** Container Apps + object storage | **$100–230** | compute-dominated; both cheap at idle |
| **Small SaaS — managed OCR** | **Azure** Container Apps + Document Intelligence | **$350–800** | Azure's $10/1k tables beats AWS/GCP |
| **Enterprise client** | **whatever they mandate** (often Azure) | varies | procurement/compliance wins |

**Bottom line on cost:** for a solo-built MVP, **GCP Cloud Run is the most
cost-effective and least-effort**. If you rely on managed document AI at volume,
**Azure is cheapest**. **AWS is rarely the cheapest here**, but it's the most
common skill and safest for hireability/resale.

---

## 7. Recommendation
1. **Building it yourself / MVP → GCP Cloud Run.** Simplest path from container to
   live URL, best free tier, cleanest scale-to-zero → lowest idle cost. Pair with
   GCS + Pub/Sub; self-host OCR or use Document AI to start.
2. **Client is enterprise / Microsoft, or you lean on managed OCR → Azure.**
   Container Apps scales to zero and **Document Intelligence is the cheapest table
   extractor**. Enterprises frequently mandate Azure anyway.
3. **You want maximum ecosystem / resume value / client already on AWS → AWS.**
   Fine and reliable; just expect to self-host OCR at scale (Textract tables are
   costly) and do a bit more wiring for scale-to-zero.

**De-risker:** keep the app a **portable Docker container** with cloud specifics
(storage, queue, OCR) behind small interfaces. Then Cloud Run ↔ Container Apps ↔
Fargate is a deployment change, not a rewrite — you can start on the cheapest and
move if a client requires otherwise.

---

## 8. For the Upwork client conversation
- Lead with **"cloud-agnostic, containerized — we deploy to your cloud of
  choice."** Enterprises love hearing they aren't locked in.
- If *you* host the MVP: **GCP Cloud Run**, cheapest to run while proving value.
- If they're a **Microsoft shop**: **Azure** (also cheapest managed OCR) — and
  it's what their procurement likely wants.
- Reliability question: **all three meet ~99.9% SLA**; the pipeline is idempotent
  and queue-backed, so a node failure just re-runs the job — no data loss.

---

### Sources (2026, directional)
- [AWS Fargate](https://aws.amazon.com/fargate/pricing/), [Lambda](https://aws.amazon.com/lambda/pricing/), [Textract](https://aws.amazon.com/textract/pricing/) pricing.
- [Google Cloud Run pricing](https://cloud.google.com/run/pricing) (2M requests/mo free), [Document AI pricing](https://cloud.google.com/document-ai/pricing).
- [Azure Container Apps pricing](https://azure.microsoft.com/pricing/details/container-apps/), [AI Document Intelligence pricing](https://azure.microsoft.com/pricing/details/ai-document-intelligence/).
- Comparison writeups: [Fargate vs Container Apps vs Cloud Run 2026](https://sliplane.io/blog/comparing-prices-aws-fargate-vs-azure-container-apps-vs-google-cloud-run); [Textract vs Document AI vs Document Intelligence 2026](https://soceton.com/blogs/aws-textract-vs-google-document-ai-vs-azure-document-intelligence).
