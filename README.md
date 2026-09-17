# Agentic Warehouse

A camera-based warehouse management system in which **every component that
reaches a decision is an independent AI agent**. Scan a QR code or a barcode;
fourteen agents each decide their own part, explain why, and pass it on.

The runnable implementation of the research proposal *Agentic AI for Multi-Agent
Collaboration in Warehouse Management Systems* (COS700, University of Pretoria).
No sensors, no conveyor — camera only.

---

## Run it

```bash
python app.py
```

Open **http://localhost:8000**. On Windows, double-click `run.bat` instead.

That one command starts the database, the API and the web interface. There is
**nothing to `pip install`** — the server runs on the Python standard library
alone. Node is needed only to *rebuild* the front end, never to run it.

On first run the console prints the administrator credentials. The account starts
on a temporary password and can do almost nothing until it is changed — a
restriction enforced by the server, not merely by the interface.

### Phone cameras

Browsers only grant camera access over HTTPS or on `localhost`, so a phone needs:

```bash
python app.py --https
```

Then open **`/connect`** on this machine — `https://localhost:8443/connect`. It
shows a QR of the LAN address, the address in text, and what to do when the phone
will not connect. Scan it with the phone's camera app. The certificate is
self-signed, so the phone warns once; choose *Advanced* and continue.

The console prints the same QR, for when a browser is not to hand.

The phone runs the whole application — it is a second workstation writing to the
same database, not a webcam feeding this screen. It keeps its own camera list on
the **Cameras** screen, because a camera id issued by one browser means nothing in
another.

### Check it works

```bash
python verify.py
```

**289 checks** on a throwaway database: the full pipeline, authentication and
roles, product CRUD, scan recovery, duplicate suppression, daily reporting, the
model bake-off, code generation, and a live HTTP server. It never touches real
data.

---

## What it does

### 1. Scanning that does not stop

Four input paths, each taking over from the one before automatically:

| | Path | When it takes over |
|---|---|---|
| 1 | Primary camera | normal |
| 2 | **Backup camera** | on error, disconnect, camera theft, or a decode stall |
| 3 | Still photo | a phone photo resolves bars a fixed-focus webcam cannot |
| 4 | Manual entry | always available, never disabled |

The **Vision Agent** decides the failover. The browser reports the symptom — only
it can see the camera — and the agent weighs that against the cameras available,
then says what it decided and why. A silent failover is indistinguishable from a
camera that never worked, so the operator is always told.

Cameras are configured per machine on the **Cameras** screen: register the built-in
webcam, a USB camera or an IP camera, mark one **primary** and one **backup**, set
the order they are tried in, and measure each one. A measurement is taken by the
browser — nothing else can open a camera — and scored by the server, so the same
camera earns the same grade whichever machine tested it.

> **Webcams and USB cameras.** These used not to attach at all while phone cameras
> worked. The cause was enumeration, not decoding: the scanner library opens the
> *system default* camera before it will list anything, so one busy camera hid every
> camera on the machine — and on Windows a USB camera is released asynchronously, so
> the next attempt to open it arrived while the driver still held it. Both are fixed,
> along with hot-plug detection, per-attempt scanner instances, a re-entrancy guard,
> and error messages that distinguish "another application has it" from "permission
> was refused" from "that camera is gone".

Behind all four paths sits the **Recovery Agent**, which repairs reads the decoder
mangled:

| Scanned | Repaired to | Strategy |
|---|---|---|
| `  789076542345\r\n` | `789076542345` | control characters stripped |
| `(01)0789…(10)27020` | `789076542345` + batch | GS1 identifiers unwrapped |
| `78907654234S` | `789076542345` | `S` read for `5` |
| `7890765423` | `789076542345` | truncated read completed |

A repair is applied on its own only at **≥80% confidence *and*** when the result
matches real stock. Below that it is offered for a person to confirm.

### 2. One presentation, one unit

A camera re-decodes about twelve times a second. Without a guard, one box held
under the lens becomes a dozen units — and it did. Two layers now prevent it: the
browser suppresses repeat reads at source, and the server enforces the rule
regardless of what any client does. The delay is configurable, deliberate repeat
entry is never suppressed, and different products are never delayed.

### 3. Fourteen agents, seven layers

| Layer | Agents |
|---|---|
| **security** | Authentication, Authorisation |
| **perception** | Scanner, **Vision**, Recovery, Classifier |
| **operations** | Inventory, Anomaly, Audit |
| **planning** | Forecast, Procurement |
| **learning** | Learning |
| **administration** | Staff |
| **assistance** | Assistant |

An agent that fails returns a `DEGRADED` decision and the pipeline carries on.
Only the Inventory Agent is on the critical path, because a silent failure there
would leave the stock figures wrong.

### 4. Five models, cross-validated

All written from scratch — no scikit-learn, no numpy:

| Model | CV accuracy | Macro F1 | Score |
|---|---|---|---|
| **Nearest Centroid (Rocchio)** | **93.7%** | 94.3% | 0.9439 |
| Multinomial Naive Bayes | 91.9% | 92.3% | 0.9241 |
| TF-IDF Logistic Regression | 91.2% | 91.9% | 0.9192 |
| Character N-Gram Naive Bayes | 90.7% | 91.0% | 0.9129 |
| TF-IDF k-Nearest Neighbours | 80.6% | 79.5% | 0.8162 |

5-fold stratified cross-validation, seed 42, on 160 labelled product names across
6 categories. **Against the original 20-sample baseline: 70% → 93.7%, a 79%
reduction in errors.**

The Learning Agent retrains as managers file products, and **refuses to promote a
model that scores worse** than the one already running.

### 5. Everything else

- **Login and staff management** — 4 roles over 18 capabilities, PBKDF2 passwords,
  per-account lockout, every movement attributed to a named person
- **Full CRUD** on products, batches, categories, staff and settings
- **Product detail pages** — history, batches, handlers, movement chart, labels
- **Daily reports** — in/out per day with net movement, split by product,
  category, staff and hour, over any date range, exportable
- **Printable labels** carrying a QR *and* a barcode for the same product
- **Audit Agent** that reconciles stock against the log and reports drift

### 6. How it compares with what you could buy instead

The **Comparison** screen measures this system against six tiers of existing
system — paper and spreadsheets, barcode hardware, scanning SDKs, enterprise WMS
platforms, RFID, and computer-vision and multi-agent research — over 26
dimensions.

It is built on one rule: **our numbers are measured, theirs are attributed.**
Every figure about this system is read from the live registry, the cross-validated
model results or the self-test, and re-derived by `python verify.py`. Every figure
about another system carries a label saying what kind of claim it is, and no
accuracy percentage is invented for any named commercial product.

**It reports the losses.** Eight dimensions are recorded as losses and three as
differences of scope:

| Where this system is behind | Why |
|---|---|
| Decode robustness | A stock ZXing decoder on a commodity lens, no preprocessing |
| Read range | A phone lens against a 30-metre imager |
| Ruggedisation | No IP rating, no drop spec, no freezer variant |
| Bulk throughput | One label in frame; RFID reads a pallet at once |
| Enterprise depth | No EDI, TMS, labour, slotting, yard or robotics |
| Enterprise identity | Local accounts only — no SSO, SAML or SCIM |
| Concurrency | One SQLite file, one writer, one node |
| Field validation | A passing self-test is not production exposure |

Where it does lead is on **what happens around the read** — recovering a bad one,
refusing a duplicate, deciding which camera to use, and recording who decided what
and why. A comparison that won every row would be a brochure.

---

## Requirements

| | |
|---|---|
| **To run** | Python 3.8+ and nothing else |
| **To rebuild the front end** | Node 18+ (only if `static/dist/` is missing) |
| **For phone cameras** | `openssl` for the self-signed certificate (ships with Git for Windows) |
| **Optional** | `pip install anthropic` for the Claude-backed assistant |

## Layout

```
app.py              entry point: server, static files, HTTPS, front-end build
api.py              65 HTTP routes, every one capability-guarded
db.py               inventory data layer
report.py           the measured comparison against the baseline system
market.py           the comparison against existing systems on the market
verify.py           289-check self-test
core/               router, database core, security, QR and barcode encoders
agents/             the 14 agents, the base framework, the orchestrator
ml/                 5 classifiers, features, metrics, k-fold evaluation
store/              users, sessions, settings, cameras
web/                React source (Vite + Tailwind + shadcn/ui)
static/dist/        the built front end, served by the Python server
templates/          the original single-page dashboard, kept at /legacy
data/warehouse.db   created on first run
reports/            the written research documents
```

Roughly **26,200 lines across 88 source files** — 15,900 of Python, 10,300 of
React.

## Documentation

| File | Contents |
|---|---|
| `SETUP.md` | Installation, step by step, and troubleshooting |
| `MVP.md` | Features, API, data model, measured accuracy, known limits |
| `PROJECT.md` | Research framing and how this maps to the proposal |
| `CLAUDE.md` | Architecture and the rules the code follows |
| `reports/Connect_Your_Phone.html` | For warehouse staff: connecting a phone and scanning with it. Printable |

## How this maps to the research proposal

Each warehouse function is an independent agent that senses, decides and
cooperates — the decentralised multi-agent system the proposal argues for, in
running code rather than in a diagram. The scanning reuses the sensing idea from
the original AUTOWARE project, with the camera alone.

Open **`/report`** in the app for the dimension-by-dimension comparison against
that centralised baseline, with every figure measured rather than estimated and
its caveats stated alongside.

---

*Mohtashim Hussain — COS700 research project, University of Pretoria.*
