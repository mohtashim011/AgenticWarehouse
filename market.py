"""
Comparison against existing warehouse systems
=============================================
Where this system stands against what a warehouse could actually buy instead.

This is a different question from the one :mod:`report` answers. That module
compares this system with **the project it replaces** — the earlier centralised,
rule-based AUTOWARE build. This one compares it with **the alternatives on the
market**: paper, barcode hardware, scanning SDKs, enterprise WMS platforms,
RFID, and the computer-vision and multi-agent work being published now.

The rule that shapes every line of this file
--------------------------------------------
**Our numbers are measured. Theirs are attributed.**

Every figure describing this system is read from the live registry, the
cross-validated model results, or the self-test — never typed in — and carries a
``file:line`` citation a reader can open. Every figure describing somebody
else's system carries an ``evidence`` label saying what kind of claim it is:

``measured``           we ran it, here, and ``verify.py`` re-runs it
``vendor-published``   the vendor publishes this figure
``industry-typical``   a widely reported operational range, not one product
``structural``         an architectural fact, verifiable by inspection
``academic``           from the published literature

No precise accuracy percentage is ever invented for a named commercial product.
Where no trustworthy number exists — decode robustness is the clearest case,
because the head-to-head comparisons that circulate are published by competing
vendors and disagree with each other — the comparison says so and falls back to
a structural statement.

Why it reports losses
---------------------
A comparison that wins every row is not a comparison, it is a brochure, and any
examiner will read it as one. This system genuinely loses on read range,
ruggedisation, bulk throughput, enterprise integration depth, concurrency and —
most importantly — field validation: a prototype with a passing self-test has no
production exposure at all against platforms running the world's largest
distribution networks. Those rows are marked ``loss`` and are shown in the same
table as the wins, not in a footnote.

Rows marked ``scope`` are neither: they are places where the two systems are
aimed at different problems, and pretending otherwise would be the subtler kind
of dishonesty.
"""

WIN = "win"
LOSS = "loss"
SCOPE = "scope"

MEASURED = "measured"
VENDOR = "vendor-published"
TYPICAL = "industry-typical"
STRUCTURAL = "structural"
ACADEMIC = "academic"


# ---------------------------------------------------------------------------
# The alternatives
# ---------------------------------------------------------------------------
TIERS = [
    {
        "key": "manual",
        "name": "Manual, paper and spreadsheets",
        "exemplars": ["Paper goods-received notes", "Excel and Google Sheets stock books",
                      "Bin cards", "Clipboard cycle counts"],
        "identifies_by": "A person reads the carton and types what they read.",
        "strengths": ["No capital cost and no licence",
                      "Works with no power, no network and no vendor",
                      "Still genuinely appropriate below a few dozen SKUs"],
        "limits": ["Error is a keying rate, not a read rate",
                   "A spreadsheet cell is overwritten in place, so no append-only "
                   "audit is architecturally possible",
                   "No attribution, no concurrency control, no roles",
                   "Nothing detects an implausible count"],
        "evidence": TYPICAL,
    },
    {
        "key": "handheld",
        "name": "Barcode hardware and a WMS behind it",
        "exemplars": ["Zebra MC9400 / TC series", "Honeywell CK65", "Datalogic Skorpio X5",
                      "Zebra DataWedge into SAP EWM, Korber, Infor"],
        "identifies_by": "A dedicated laser or imager engine decodes on-device and "
                         "injects the string into the focused field.",
        "strengths": ["Extremely fast and reliable decode on a purpose-built engine",
                      "Long read range and ruggedised for warehouse conditions",
                      "Decades of field validation at enormous scale"],
        "limits": ["A dedicated device must be bought per operator",
                   "The capture path has no decision layer — keystroke output goes "
                   "into whatever field has focus, so there is architecturally "
                   "nowhere to hold a verdict or a confidence",
                   "One scan engine per device, so there is no second sensor to "
                   "fall back to at runtime — in practice the redundancy is a spare "
                   "handheld on the shelf rather than a decision the software makes",
                   "Classification is a master-data lookup, not learned"],
        "evidence": VENDOR,
    },
    {
        "key": "sdk",
        "name": "Mobile and browser scanning SDKs",
        "exemplars": ["Scandit", "Dynamsoft Barcode Reader", "Google ML Kit",
                      "Apple VisionKit", "Scanbot"],
        "identifies_by": "Frames from a consumer camera are decoded on-device by a "
                         "proprietary or open-source decoder.",
        "strengths": ["Runs on hardware the warehouse already owns",
                      "Decode engines are heavily optimised and widely validated",
                      "Broad symbology coverage"],
        "limits": ["A decode component only: no inventory state machine, no "
                   "duplicate-read policy, no audit log, no user identity, no roles",
                   "Camera failover is not the SDK's decision, and the "
                   "'runs but decodes nothing' failure raises no error in any of them",
                   "The decode model is the vendor's and cannot be retrained by the "
                   "integrator",
                   "Licensing varies and matters for offline use: some commercial "
                   "SDKs revalidate a cached licence on a schedule, while Google ML "
                   "Kit and Apple VisionKit are free platform components with no "
                   "licence server at all"],
        "evidence": VENDOR,
    },
    {
        "key": "wms",
        "name": "Commercial and ERP warehouse management systems",
        "exemplars": ["SAP EWM", "Oracle WMS Cloud", "Manhattan Active", "Blue Yonder",
                      "Odoo Inventory", "Fishbowl", "Zoho Inventory"],
        "identifies_by": "It does not scan. It consumes decoded strings from the "
                         "hardware or SDK tier and resolves them against master data.",
        "strengths": ["Enormous execution depth: EDI, ASN, TMS, labour, slotting, "
                      "waving, yard and dock, multi-site, robotics",
                      "Proven at the largest scale in the world",
                      "Full enterprise identity, SSO and provisioning integration"],
        "limits": ["Perception is architecturally out of scope, so camera failover "
                   "and decode recovery cannot exist within it",
                   "The flagship products are increasingly delivered as cloud "
                   "SaaS, though on-premises and private-cloud options remain "
                   "available for several",
                   "Time to first scan is measured in months",
                   "Judgement lives in configuration, so the reason a transaction "
                   "was accepted is reconstructible only by an expert reading it"],
        "evidence": STRUCTURAL,
    },
    {
        "key": "rfid",
        "name": "RFID identification",
        "exemplars": ["Zebra RFD40/RFD90", "Impinj R700", "Honeywell IH45",
                      "Walmart, Lululemon, Inditex programmes"],
        "identifies_by": "A reader powers a passive UHF tag, which backscatters its "
                         "EPC identifier. No line of sight needed.",
        "strengths": ["Bulk reading — hundreds of tags a second, through cartons",
                      "No line of sight and no operator aiming",
                      "Transformative for apparel and high-turnover retail"],
        "limits": ["Cannot identify an untagged item at all: identity requires a "
                   "consumable applied to every unit first",
                   "Metal reflects and liquids attenuate UHF, shrinking read zones",
                   "Tag-to-product binding is trust-based and unverifiable by the "
                   "reader, so a mis-applied tag produces confidently wrong stock",
                   "Suppression of stray reads is a threshold in middleware, not a "
                   "per-read decision with a reason"],
        "evidence": TYPICAL,
    },
    {
        "key": "vision",
        "name": "Computer-vision and agentic AI systems",
        "exemplars": ["Covariant", "Pensa", "Gather AI", "Verity", "Fizyr",
                      "InvAgent and the multi-agent inventory literature"],
        "identifies_by": "Appearance rather than symbol — detection and segmentation "
                         "models over fixed, robot- or drone-mounted cameras. The "
                         "multi-agent literature does not identify stock at all.",
        "strengths": ["Identifies unlabelled and boxed stock that no code-based "
                      "system can see",
                      "Detects damage, shelf gaps and pose, not just identity",
                      "The strongest published direction for warehouse autonomy"],
        "limits": ["Model-centric rather than decision-centric: the published output "
                   "is a class and a confidence. Some platforms ship review and audit "
                   "tooling, but a per-transaction record of which component decided "
                   "what, with its reasoning, is not a documented property of the tier",
                   "Published accuracy figures generally arrive without a dataset, "
                   "split or seed, so a warehouse cannot re-derive them",
                   "Retraining is a vendor-owned offline pipeline, with no in-product "
                   "regression gate",
                   "The multi-agent research strand is almost entirely simulation: no "
                   "perception, no authentication, no persistence, no audit trail"],
        "evidence": ACADEMIC,
    },
]


# ---------------------------------------------------------------------------
# Facts about this system, counted rather than written down
# ---------------------------------------------------------------------------
def _facts(ml_results):
    """Read the live numbers.

    Hard-coding these was tried once and they were wrong within a day of adding
    an agent. A comparison whose own figures drift is worse than one that omits
    them, so everything countable is counted at render time.
    """
    # Note what is NOT here: a check count. verify.py knows how many checks it
    # ran only after running them, and a literal typed in here drifted the day
    # a check was added -- which is exactly the failure this module claims to
    # avoid. The reproducibility row therefore names what the self-test asserts
    # rather than how many times it asserts something.
    facts = {"agents": 0, "layers": 0, "critical": [], "capabilities": 0,
             "roles": 0, "strategies": 0}

    try:
        from agents.base import registry
        agents = registry.all()
        facts["agents"] = len(agents)
        facts["layers"] = len({a.layer for a in agents})
        facts["critical"] = [a.name for a in agents if a.critical]
    except Exception:                        # noqa: BLE001
        pass

    try:
        from store import users as user_store
        facts["capabilities"] = len(set().union(*user_store.CAPABILITIES.values()))
        facts["roles"] = len(user_store.ROLES)
    except Exception:                        # noqa: BLE001
        pass

    # RecoveryAgent.STRATEGIES is the tuple decide() actually iterates, so this
    # counts executed strategies rather than remembered ones. It is deliberately
    # NOT wrapped in a bare except that falls back to a literal: that hid an
    # AttributeError here for as long as the attribute did not exist, and a
    # silent fallback to the number you hoped for is worse than a crash.
    from agents.recovery_agent import RecoveryAgent
    facts["strategies"] = len(RecoveryAgent.STRATEGIES)

    winner = (ml_results or {}).get("models", [{}])[0] if (ml_results or {}).get("models") else {}
    dataset = (ml_results or {}).get("dataset", {})
    facts["model"] = winner.get("name", "-")
    facts["accuracy"] = winner.get("cv_accuracy", 0.0)
    facts["macro_f1"] = winner.get("macro_f1", 0.0)
    facts["samples"] = dataset.get("total", 0)
    facts["classes"] = dataset.get("classes", 0)
    facts["models"] = len((ml_results or {}).get("models", []))
    facts["folds"] = (ml_results or {}).get("folds", 5)
    facts["seed"] = (ml_results or {}).get("seed", 42)
    return facts


def _row(dimension, verdict, ours, evidence, why, tiers, group):
    return {
        "dimension": dimension,
        "verdict": verdict,
        "ours": ours,
        "ours_evidence": evidence,
        "why_it_matters": why,
        "tiers": tiers,
        "group": group,
    }


def _dimensions(f):
    """The comparison itself, grouped so a reader can find a theme."""
    critical = " and ".join(f["critical"]) or "no agent"

    return [
        # -- identification ------------------------------------------------
        _row(
            "What must be on the item before it can be identified",
            SCOPE,
            "A printed QR code or 1-D barcode. The system prints its own labels, "
            "so an unlabelled product can be brought into the scheme in one step.",
            "core/qrcode.py, core/barcode.py, api.py /api/products/<no>/label",
            "This is the precondition every other row depends on. A camera cannot "
            "read what carries no code, and saying so first is what makes the rest "
            "of the table credible.",
            {
                "manual": "Human-legible text. Nothing needs applying, but nothing is verified either.",
                "handheld": "A printed symbol, same as here.",
                "sdk": "A printed symbol, same as here.",
                "wms": "Whatever the capture tier supplies.",
                "rfid": "A tag applied to every single unit before it enters the system.",
                "vision": "Nothing — appearance alone. The clear win for unlabelled and boxed stock.",
            },
            "identification",
        ),
        _row(
            "Maximum read range",
            LOSS,
            "Arm's length. A commodity camera lens, and no software changes that.",
            "web/src/hooks/useCamera.js (getUserMedia video, no optics)",
            "A picker who must walk to every pallet is slower than one reading a "
            "top-stacked carton from the aisle floor.",
            {
                "manual": "Arm's length.",
                "handheld": "Tens of metres on an extended-range engine — a decisive advantage.",
                "sdk": "Beyond arm's length with vendor optics tuning, but still a phone lens.",
                "wms": "Not applicable.",
                "rfid": "Metres, through cartons, with no aiming at all.",
                "vision": "Whatever the mounted optics allow.",
            },
            "identification",
        ),
        _row(
            "Bulk throughput without line of sight",
            LOSS,
            "One label in frame at a time. Not contested.",
            "web/src/hooks/useCamera.js (single-frame decode)",
            "Counting a full pallet is a different problem from receiving a carton, "
            "and no camera architecture solves it.",
            {
                "manual": "One item at a time, by hand.",
                "handheld": "One symbol at a time, or a small burst.",
                "sdk": "A small batch per frame at best.",
                "wms": "Not applicable.",
                "rfid": "Hundreds per second through a dock portal. RFID wins outright, by design.",
                "vision": "A whole shelf per frame.",
            },
            "identification",
        ),
        _row(
            "Ruggedisation and environmental envelope",
            LOSS,
            "A consumer laptop or phone. No IP rating, no drop specification, no "
            "freezer variant.",
            "structural — the system runs in a browser on existing hardware",
            "A device that fails in a chiller or after one drop onto concrete costs "
            "more in downtime than it saved in capital.",
            {
                "manual": "Paper survives most things.",
                "handheld": "IP65/IP68, multi-metre drop specs, freezer variants. An outright win.",
                "sdk": "As rugged as the phone it runs on.",
                "wms": "Not applicable.",
                "rfid": "Industrial readers are built for the environment.",
                "vision": "Fixed installations are specified for the site.",
            },
            "identification",
        ),

        # -- capture resilience ---------------------------------------------
        _row(
            "Raw decode robustness under adverse capture",
            LOSS,
            "A general-purpose open-source decoder (ZXing, via html5-qrcode) on a "
            "commodity lens, reading whole frames at roughly 8-12 scans a second. "
            "It has no super-resolution, no deblurring, no multi-frame fusion and "
            "no trained localiser. A blurred, torn, low-contrast or steeply angled "
            "label that a purpose-built engine recovers will simply not read here.",
            "web/src/hooks/useCamera.js (ZXing via html5-qrcode, no preprocessing)",
            "This is the row a vendor would leave out, so it is the row that has to "
            "be here. Everything this system does well happens AROUND the read; the "
            "read itself is the weakest link in the chain, and no amount of agent "
            "architecture improves it. The honest caveat cuts both ways: there is no "
            "neutral published benchmark for this tier either -- the head-to-head "
            "comparisons that exist are published by competing vendors and disagree "
            "-- so this is a structural loss, not a measured one.",
            {
                "manual": "No decode at all; a human reads the printed text, which "
                          "is far more robust to damage and far less accurate.",
                "handheld": "Purpose-built optics, illumination and decode silicon. "
                            "The clear leader, and the reason the tier exists.",
                "sdk": "Years of optimisation on exactly this problem, including "
                       "blur and low-light handling well beyond a stock decoder.",
                "wms": "Not applicable — it never sees an image.",
                "rfid": "No optical decode; damage to a label is irrelevant, though "
                        "metal and liquid create their own failure modes.",
                "vision": "Trained detectors localise a symbol far better than a "
                          "classical decoder before it is even read.",
            },
            "identification",
        ),
        _row(
            "Capture-device failure modes actually handled",
            WIN,
            "All four: it refuses to start, its track ends when unplugged, it is "
            "muted by another application, and it runs while decoding nothing. The "
            "fourth raises no error anywhere by construction, so only a watchdog "
            "catches it.",
            "web/src/hooks/useCamera.js (watchdog, ended/mute listeners); "
            "agents/vision_agent.py SYMPTOMS",
            "The fourth mode is the one that costs a shift: the picture looks fine, "
            "the operator keeps presenting labels, and nothing is being counted.",
            {
                "manual": "Not applicable — no capture device.",
                "handheld": "None at runtime. One engine per device; a failure is an RMA.",
                "sdk": "Start errors and track state are surfaced; the decode-nothing "
                       "case is left to the integrator and is usually unhandled.",
                "wms": "Out of scope — the WMS never sees a camera.",
                "rfid": "Reader health monitoring, but no automatic capture failover.",
                "vision": "Camera health is monitored in fixed installations.",
            },
            "resilience",
        ),
        _row(
            "Automatic failover to a second capture device",
            WIN,
            "Yes, and the decision is an agent's rather than a hard-coded rule. The "
            "browser reports the symptom; the Vision Agent weighs the configured "
            "roles, the measured grades, what has already been tried and how long "
            "the symptom has lasted, then returns switch, keep or fall back — with "
            "the reasoning the operator reads.",
            "agents/vision_agent.py; api.py POST /api/vision/failover; "
            "store/cameras.py scanner_order",
            "A silent failover is indistinguishable from a camera that never "
            "worked, so the reasoning matters as much as the switch.",
            {
                "manual": "Not applicable.",
                "handheld": "Structurally absent — one engine per device.",
                "sdk": "No SDK decides to switch cameras; it is not their job.",
                "wms": "Out of scope.",
                "rfid": "Antenna redundancy in fixed portals, not a per-read decision.",
                "vision": "Camera arrays are redundant by installation, not by decision.",
            },
            "resilience",
        ),
        _row(
            "Recovery from an unreadable or unresolvable code",
            WIN,
            "%d ordered repair strategies — control-character stripping, GS1 "
            "unwrapping, check-digit repair, prefix trimming, character-confusion, "
            "transposition and fuzzy name match — stopping at the first that yields "
            "a code this warehouse actually holds. Below the confidence threshold "
            "the operator confirms. Above that threshold, and only when the "
            "repaired code matches real stock, it is applied without asking -- "
            "the threshold is a setting, and the trace records which strategy "
            "fired and how confident it was."
            % f["strategies"],
            "agents/recovery_agent.py (strategy order, AUTO_ACCEPT); "
            "measured in verify.py",
            "In every other tier the answer is that the operator retypes it — which "
            "returns the transaction to manual keying error rates at exactly the "
            "moment the system has already shown it is struggling.",
            {
                "manual": "Retype it.",
                "handheld": "Rescan, or retype it.",
                "sdk": "Rescan. Repair is not the SDK's concern.",
                "wms": "The string either matches master data or it is rejected.",
                "rfid": "A failed read is simply a missing read.",
                "vision": "Fall back to a code or a tag.",
            },
            "resilience",
        ),
        _row(
            "Duplicate-read policy",
            WIN,
            "Enforced in two independent places. The browser suppresses repeats at "
            "source; the server enforces the same window per (user, product, mode, "
            "batch) regardless of client. The suppression stamp is written only "
            "after the stock write succeeds, so a failed scan can be retried at "
            "once, and deliberate input is never suppressed — typing a code five "
            "times is how someone counts five boxes in.",
            "agents/orchestrator.py (server guard, post-commit stamp); "
            "web/src/pages/Scanner.jsx (browser gate); measured in verify.py",
            "A camera re-decodes about twelve times a second. Writing the stamp "
            "before the commit would turn an over-count into a silent under-count, "
            "which is the worse failure.",
            {
                "manual": "No scan, so no duplicates — and no verification either.",
                "handheld": "A trigger pull is one read; the problem does not arise, "
                            "and neither does continuous scanning.",
                "sdk": "Left entirely to the integrator.",
                "wms": "Idempotency is a configuration concern at the transaction layer.",
                "rfid": "Stray reads are filtered by RSSI thresholds in middleware.",
                "vision": "Frame-to-frame tracking, tuned per deployment.",
            },
            "resilience",
        ),
        _row(
            "Identity resolution strictness",
            WIN,
            "A QR payload and a printed barcode resolve to one product record, in "
            "both directions, through exact match then user-set links then a strict "
            "check-digit variant rule. A TRAILING digit is dropped only when it is "
            "genuinely the check digit for what remains (a leading zero is dropped "
            "freely, because EAN-13 and UPC-A are the same digits), and only for "
            "numeric codes of barcode length — without that restriction, 09000019 resolved onto the "
            "unrelated product 900001 and the log recorded the resolved number, so "
            "the error was invisible afterwards.",
            "db.py resolve_productno and _code_variants; asserted in verify.py",
            "Split or wrongly-merged stock records are the most common way a "
            "warehouse count silently goes wrong.",
            {
                "manual": "Whatever was typed.",
                "handheld": "The decoded string, resolved by WMS master data.",
                "sdk": "The decoded string. Resolution is not in scope.",
                "wms": "GTIN, SSCC and licence-plate resolution — mature and strong.",
                "rfid": "The EPC is exact, but its binding to the product is not verifiable.",
                "vision": "Ambiguous for visually identical variants, so most "
                          "deployments fall back to a code when exact identity matters.",
            },
            "resilience",
        ),

        # -- decisions and transparency ---------------------------------------
        _row(
            "Per-decision reasoning stored with the transaction",
            WIN,
            "Every agent returns a verdict, a confidence and plain-language "
            "reasoning, and the whole trace is serialised onto the log row for the "
            "stock movement it caused. Any number on the dashboard can be traced "
            "back to the agent that produced it, months later, without a specialist.",
            "agents/base.py Decision.to_dict; db.py add_log (trace column)",
            "This is the research contribution in running code rather than in a "
            "diagram, and it is the row where the gap is widest.",
            {
                "manual": "Nothing. Only that the number is now different.",
                "handheld": "Structurally absent — keystrokes carry no verdict.",
                "sdk": "Structurally absent.",
                "wms": "Narrative operational briefs, not a per-transaction record.",
                "rfid": "Structurally absent.",
                "vision": "A bounding box and a score, not a chain of named decisions. "
                          "In the LLM literature, chain-of-thought produced at "
                          "inference time and not persisted.",
            },
            "transparency",
        ),
        _row(
            "Decentralised decision-making",
            WIN,
            "%d agents across %d layers, each in its own file with one "
            "responsibility. The orchestrator coordinates but never decides. An "
            "agent that raises returns a DEGRADED decision and the pipeline "
            "continues; %s is deliberately on the critical path, because a silent "
            "failure there would leave the stock figures wrong."
            % (f["agents"], f["layers"], critical),
            "agents/*.py, agents/base.py, agents/orchestrator.py; "
            "counts read from the live registry",
            "Containment is the practical payoff: a warehouse that stops receiving "
            "stock because the forecast divided by zero is worse than one that "
            "receives stock without a forecast.",
            {
                "manual": "One person, no decomposition.",
                "handheld": "A capture device and a monolithic WMS behind it.",
                "sdk": "A single decode component.",
                "wms": "Distributed microservices, but judgement lives in "
                       "configuration rather than in discrete reasoning agents.",
                "rfid": "Readers and middleware filters.",
                "vision": "The multi-agent literature is architecturally close — but "
                          "almost entirely in simulation, with no perception layer.",
            },
            "transparency",
        ),
        _row(
            "Audit immutability and attribution",
            WIN,
            "Append-only. No code path deletes a log row: an undone scan stays "
            "visible and its reversal is written as its own forward entry. Every "
            "write that changes stock records the account and the username, and an "
            "Audit Agent reconciles stock against the log and reports drift without "
            "ever repairing it.",
            "db.py add_log and undo; agents/audit_agent.py",
            "An agent that quietly edits stock to make its own checks pass is worse "
            "than no agent at all, which is why reconciliation is read-only.",
            {
                "manual": "Structurally impossible — a cell is overwritten in place.",
                "handheld": "Whatever the WMS behind it records.",
                "sdk": "None.",
                "wms": "Generally strong at tier one; depth of lot and serial "
                       "audit varies considerably across the SMB tier and is worth "
                       "checking per product rather than assuming.",
                "rfid": "Read events are logged; business attribution comes from elsewhere.",
                "vision": "Detections are logged; attribution is not the model's concern.",
            },
            "transparency",
        ),

        # -- learning ----------------------------------------------------------
        _row(
            "Classification: learned, rule-based or absent",
            WIN,
            "%d classifiers written from scratch — no scikit-learn, no numpy — are "
            "cross-validated on identical data and the best is selected. %s leads "
            "at %.1f%% accuracy and %.1f%% macro-F1 under %d-fold stratified "
            "cross-validation, seed %d, on %d labelled product names across %d "
            "categories, with the vectoriser fitted inside each fold."
            % (f["models"], f["model"], f["accuracy"] * 100, f["macro_f1"] * 100,
               f["folds"], f["seed"], f["samples"], f["classes"]),
            "ml/registry.py, ml/evaluate.py, ml/models/*; re-derived by verify.py",
            "The protocol is published with the number. A figure without its "
            "dataset, split and seed is not a measurement, it is a claim.",
            {
                "manual": "Whatever a human typed, with no consistency check.",
                "handheld": "Absent from the device; a master-data lookup in the WMS.",
                "sdk": "Absent. An SDK returns a payload, never a meaning.",
                "wms": "Master data or configured rules, not a learned model.",
                "rfid": "Absent.",
                "vision": "Learned, and far more capable — but vendor-owned, and "
                          "published without a reproducible protocol.",
            },
            "learning",
        ),
        _row(
            "Who is allowed to write a category",
            WIN,
            "The model only ever suggests. A category a manager filed is fact and is "
            "never overridden; an unseen product is filed as Uncategorised with a "
            "suggestion attached for a person to accept or change.",
            "agents/classifier_agent.py; asserted in verify.py",
            "Nobody re-checks a value that already looks authoritative. Keeping "
            "guesses visibly separate from facts is what makes the data trustworthy.",
            {
                "manual": "The person typing.",
                "handheld": "Not applicable.",
                "sdk": "Not applicable.",
                "wms": "A master-data steward.",
                "rfid": "Not applicable.",
                "vision": "The model writes its class, usually with a confidence "
                          "threshold rather than a human gate.",
            },
            "learning",
        ),
        _row(
            "Retraining with explicit regression protection",
            WIN,
            "Every category a manager assigns becomes a labelled example. The "
            "Learning Agent retrains, compares against the model actually running, "
            "and refuses to promote one more than the stated tolerance worse — the "
            "evaluation is still recorded, because a refusal is a result worth "
            "keeping, and the summary reports the live model rather than the "
            "rejected candidate.",
            "ml/registry.py REGRESSION_TOLERANCE and the promotion gate; "
            "agents/learning_agent.py",
            "Accuracy improves with use instead of decaying as the product range "
            "drifts away from the training set — and cannot silently get worse.",
            {
                "manual": "No model to retrain.",
                "handheld": "Decode parameters are configured, not learned.",
                "sdk": "The vendor's model; operator corrections cannot become data.",
                "wms": "No documented in-product retraining loop from operator corrections.",
                "rfid": "No model.",
                "vision": "Retraining is a vendor-owned offline pipeline, typically "
                          "with no in-product gate that refuses a worse model.",
            },
            "learning",
        ),

        # -- security ----------------------------------------------------------
        _row(
            "Authentication and authorisation hardness",
            WIN,
            "PBKDF2-HMAC-SHA256 at 240,000 rounds with a per-user salt and the cost "
            "stored in the hash; session tokens kept only as SHA-256 fingerprints; "
            "HttpOnly SameSite=Lax cookies, Secure over TLS; per-account lockout "
            "after 5 failures; %d roles over %d capabilities declared per route "
            "rather than per role; both security agents fail closed."
            % (f["roles"], f["capabilities"]),
            "core/security.py, store/users.py, agents/auth_agent.py; "
            "measured in verify.py",
            "An audit trail that cannot say who acted is not an audit trail.",
            {
                "manual": "Everyone who can open the file can change stock.",
                "handheld": "Device and WMS login, typically enterprise-grade.",
                "sdk": "None — not the SDK's concern.",
                "wms": "Enterprise-grade, and far beyond this on integration.",
                "rfid": "Reader access control; business identity comes from the WMS.",
                "vision": "Platform-dependent.",
            },
            "security",
        ),
        _row(
            "Enterprise identity integration (SSO, SAML, SCIM, directory sync)",
            LOSS,
            "None. Local accounts only.",
            "store/users.py — no federation of any kind",
            "Any organisation past a certain size provisions and de-provisions "
            "centrally, and a system that cannot participate becomes a manual "
            "off-boarding risk.",
            {
                "manual": "Not applicable.",
                "handheld": "Integrated with the enterprise directory.",
                "sdk": "Not applicable.",
                "wms": "Full SSO, SAML/OIDC, SCIM provisioning. An outright win.",
                "rfid": "Via the WMS.",
                "vision": "Platform-dependent.",
            },
            "security",
        ),

        # -- deployment ---------------------------------------------------------
        _row(
            "Runtime dependencies and offline operation",
            WIN,
            "Zero third-party runtime packages — the Python standard library only. "
            "The React application, the scanner engine and its icons are built into "
            "static/dist and served from the same origin, so the app itself fetches "
            "nothing from an external host. Two caveats, stated rather than buried: "
            "the legacy fallback page kept at /legacy still links Font Awesome from "
            "a CDN, and requirements.txt lists the optional anthropic package on an "
            "uncommented line, so `pip install -r` would fetch it. The server never "
            "requires it and degrades to a local responder when it is absent.",
            "app.py; static/dist served same-origin; templates/index.html:9 links "
            "a CDN stylesheet; requirements.txt:11",
            "A warehouse with an intermittent link keeps working, and there is no "
            "licence server anywhere in the path.",
            {
                "manual": "Fully offline. The universal fallback.",
                "handheld": "The device decodes offline; the WMS transaction usually "
                            "needs the Wi-Fi fabric.",
                "sdk": "ML Kit and VisionKit run fully offline; some commercial "
                       "SDKs revalidate a cached licence on a schedule.",
                "wms": "Flagship products are increasingly cloud SaaS; several "
                       "still offer on-premises or private-cloud deployment.",
                "rfid": "Readers are local; middleware and WMS usually are not.",
                "vision": "Usually cloud-connected for model updates and telemetry.",
            },
            "deployment",
        ),
        _row(
            "Hardware needed before the first scan",
            SCOPE,
            "A device the warehouse already owns, with a camera and a browser. "
            "Nothing to buy, nothing to provision.",
            "app.py — one command; the front end is served to any browser",
            "Cost per additional scanning station is the cost of a device somebody "
            "already has in their pocket.",
            {
                "manual": "Nothing — the only tier that also wins this row.",
                "handheld": "A rugged terminal per operator, plus cradles, spare "
                            "batteries and a service contract.",
                "sdk": "Also an existing device — a genuine tie.",
                "wms": "Whatever the capture tier requires.",
                "rfid": "Readers, antennas, and a tag on every single unit.",
                "vision": "Camera arrays, edge or GPU compute, site calibration.",
            },
            "deployment",
        ),
        _row(
            "Time from a bare machine to the first successful scan",
            SCOPE,
            "One command. The database is created, the front end is built if its "
            "source changed, and the API and app are served from one origin.",
            "app.py; SETUP.md",
            "Stated as MVP scope against enterprise-programme scope. It is a real "
            "asymmetry, but it is not a like-for-like efficiency claim: the two are "
            "delivering very different amounts of function.",
            {
                "manual": "Immediate, and that is exactly why it persists.",
                "handheld": "Device provisioning plus the WMS programme behind it.",
                "sdk": "Days for a developer, then the surrounding system is still to build.",
                "wms": "Commonly planned in months.",
                "rfid": "Tagging programme first, then infrastructure.",
                "vision": "Site survey, mounting and calibration.",
            },
            "deployment",
        ),
        _row(
            "Data residency and tenancy",
            WIN,
            "One SQLite file on the machine the warehouse controls. Single-tenant "
            "by construction; nothing leaves the origin.",
            "core/dbcore.py; data/warehouse.db",
            "For defence, pharmaceutical and sovereign-data operations this decides "
            "the procurement regardless of feature depth.",
            {
                "manual": "On the premises, in a filing cabinet.",
                "handheld": "Wherever the WMS lives.",
                "sdk": "On the device, but licensing calls out.",
                "wms": "Multi-tenant SaaS at tier one.",
                "rfid": "Wherever the middleware and WMS live.",
                "vision": "Usually vendor cloud.",
            },
            "deployment",
        ),

        # -- evidence -----------------------------------------------------------
        _row(
            "Reproducibility of the performance claims",
            WIN,
            "A single command re-runs the whole system on a throwaway database "
            "and exits non-zero if anything fails: the scan pipeline, the "
            "duplicate guard, the seven repair strategies, camera registration "
            "and ordering, the Vision Agent's failover decisions, the "
            "authentication and role rules, a live HTTP server, and the "
            "five-model bake-off — whose accuracies and ranking are re-derived "
            "rather than read from a file. It also re-counts the agents and the "
            "HTTP routes and fails if the documentation disagrees.",
            "verify.py; the bake-off is re-run per invocation and the "
            "documented agent and route counts are checked against the live "
            "registry and router",
            "This is an asymmetry in evidence quality, not in capability. No vendor "
            "in the hardware, SDK, WMS or RFID tiers publishes a reproducible "
            "protocol for its accuracy claims — but that does not make their "
            "systems worse, only their numbers harder to check.",
            {
                "manual": "No claims to reproduce.",
                "handheld": "Spec sheets, no reproducible protocol.",
                "sdk": "The two most-cited benchmarks are each published by a "
                       "competing vendor and they disagree about the same product.",
                "wms": "Feature matrices rather than measurements.",
                "rfid": "Read-rate figures without a published corpus.",
                "vision": "Accuracy without a dataset, split or seed.",
            },
            "evidence",
        ),
        _row(
            "Field validation at scale",
            LOSS,
            "None. A prototype with a passing self-test and no production exposure "
            "whatsoever.",
            "structural — this is a research implementation",
            "This is the row that keeps the rest honest. Billions of scans a year "
            "across millions of devices, and the largest distribution networks in "
            "the world, are not something a self-test substitutes for.",
            {
                "manual": "Centuries.",
                "handheld": "Decades, at industrial scale.",
                "sdk": "Very large scale across retail and logistics. Vendors "
                       "publish volume figures; they are not independently audited, "
                       "so none is reproduced here.",
                "wms": "The world's largest distribution networks.",
                "rfid": "Thousands of sites across global retail programmes.",
                "vision": "Large and growing industrial deployment.",
            },
            "evidence",
        ),
        _row(
            "Enterprise execution depth",
            LOSS,
            "Out of scope. Receiving, issuing, batches, reorder points, forecasting "
            "and reporting — and nothing beyond that.",
            "structural — the MVP boundary is deliberate",
            "EDI and ASN, TMS and carrier integration, labour management, slotting, "
            "wave and cluster picking, yard and dock scheduling, multi-site "
            "inventory and robotics control are all absent, and the gap is enormous.",
            {
                "manual": "Also absent.",
                "handheld": "Provided by the WMS behind it.",
                "sdk": "Absent.",
                "wms": "An outright win, and not a close one.",
                "rfid": "Provided by the WMS behind it.",
                "vision": "Focused on perception, not execution.",
            },
            "scale",
        ),
        _row(
            "Scale and concurrency ceiling",
            LOSS,
            "One SQLite file, one writer lock, one node. Right for a single "
            "facility; wrong for a distribution network.",
            "core/dbcore.py — WAL mode and a Python-level writer lock",
            "An honest loss, and one worth pairing with the observation that the "
            "two designs are aimed at facilities of very different sizes.",
            {
                "manual": "Breaks down past a few dozen SKUs.",
                "handheld": "Bounded by the WMS.",
                "sdk": "Not applicable.",
                "wms": "Distributed microservices with zero-downtime updates.",
                "rfid": "Bounded by the middleware.",
                "vision": "Bounded by the compute fleet.",
            },
            "scale",
        ),
    ]


def market_comparison(ml_results=None):
    """Assemble the comparison against existing systems."""
    f = _facts(ml_results)
    rows = _dimensions(f)

    wins = [r for r in rows if r["verdict"] == WIN]
    losses = [r for r in rows if r["verdict"] == LOSS]
    scoped = [r for r in rows if r["verdict"] == SCOPE]

    return {
        "headline": {
            "dimensions": len(rows),
            "wins": len(wins),
            "losses": len(losses),
            "scope": len(scoped),
            "tiers": len(TIERS),
            "agents": f["agents"],
            "layers": f["layers"],
            "accuracy": f["accuracy"],
            "macro_f1": f["macro_f1"],
            "model": f["model"],
            "strategies": f["strategies"],
            "capabilities": f["capabilities"],
            "roles": f["roles"],
        },
        "tiers": TIERS,
        "dimensions": rows,
        "groups": ["identification", "resilience", "transparency", "learning",
                   "security", "deployment", "evidence", "scale"],
        "evidence_key": {
            MEASURED: "Measured here, and re-derived by verify.py on every run.",
            VENDOR: "A figure the vendor publishes.",
            TYPICAL: "A widely reported operational range, not one product's claim.",
            STRUCTURAL: "An architectural fact, verifiable by inspection.",
            ACADEMIC: "From the published literature.",
        },
        "caveats": [
            "Every figure describing this system is measured here and re-derived by "
            "verify.py. Every figure describing another system is attributed, and "
            "no precise accuracy percentage is claimed for any named commercial "
            "product.",
            "Where no trustworthy number exists the comparison says so rather than "
            "inventing one. Decode robustness is the clearest case, and it is "
            "recorded as a loss on structural grounds: the head-to-head benchmarks "
            "that circulate are published by competing vendors and disagree, so "
            "there is no neutral figure to quote for anyone in the table.",
            "%d of %d dimensions are recorded as losses and %d as differences of "
            "scope. A comparison that wins every row is a brochure, not a "
            "comparison." % (len(losses), len(rows), len(scoped)),
            "The classifier accuracy describes the current corpus of %d product "
            "names under %d-fold stratified cross-validation with seed %d, and will "
            "move as more products are filed. It is not a decode accuracy: decode "
            "is a property of the ZXing library, shared with much of the SDK tier."
            % (f["samples"], f["folds"], f["seed"]),
            "This system has no production deployment. The comparison is of "
            "architecture and measured behaviour, not of operational track record.",
        ],
    }
