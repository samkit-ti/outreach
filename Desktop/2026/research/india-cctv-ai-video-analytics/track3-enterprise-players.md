# Track 3 — Enterprise / commercial CCTV video-analytics players in India
Competitive landscape for a founder deciding what to build. Compiled 2026-11-11. Product reality over marketing copy.
Sources: WebSearch snippets + direct page fetches; Entrackr/Tofler/Tracxn/Inc42 figures as surfaced by search. Items marked **[stale]** are pre-2023. Search budget was exhausted mid-run; gaps flagged as "not verified".

---

## 0. Structural context (read first)

| Fact | Detail | Source |
|---|---|---|
| Market size | India CCTV+surveillance ~$2–4B (2025), growing 8–17%; AI-analytics slice ~34% CAGR toward ~$3B by 2033 | cofacto.ai (Aug 2026) |
| **STQC rule, 1 Apr 2026** | All new internet-connected cameras/recorders sold in India must be STQC-certified (IS 13252-1 / MeitY ERs). Chinese-origin SoC/firmware not being cleared → Hikvision, Dahua, TP-Link have zero certified models; ~33% of market share transferring to CP Plus, Prama, Matrix, etc. Installed base not required to be removed. | cybersecuritynews, ptcnews, cofacto |
| Beneficiary | CP Plus (Aditya Infotech, listed) FY26 revenue ₹4,221 Cr (+35.6%); share of internet-connected segment 20.8% (FY25) → 45.4% (Q4 FY26) | cofacto |
| Value-chain economics | Hardware >60% of revenue but valued 0.5–1x; recurring analytics software valued 3–5x, >70% GM. Analytics subscriptions "$5–30/camera/month standard, $20–50 specialised" (global framing) | cofacto |
| Cash-conversion warning | CP Plus EBITDA 14.8% → OCF ~1.9%; 51.7-day CCC. Sector revenue tends to sit in receivables/inventory | cofacto |
| Regulatory demand drivers | RBI 180-day retention + camera placement rules for banks; CBSE (Jul 2025) mandatory CCTV in all affiliated schools, 15-day retention; DPDP Rules 2025 push "no face/biometric" positioning | Videonetics PR (Mar 2026), careers360, agrexai |

**Implication for a founder:** the hardware layer is being reshuffled by regulation (brownfield Hikvision/Dahua estates stay in place for years; new installs go to CP Plus/Prama/Matrix). A camera-agnostic analytics layer that runs on *both* the legacy Chinese base and the new STQC base is the only position not exposed to that reshuffle.

---

## 1. Indian company profiles

### 1.1 Horizontal "make existing CCTV smart" platforms

#### Wobot.ai (Wobot Intelligence, Delhi/US)
- **Does:** SOP/compliance video analytics — hygiene (hairnet/glove/handwash), cleaning schedules, queue, drive-thru, safety, productivity. Checklist-driven; "WoBot" agentic layer; Oct 2026 partnership to run on SiMa.ai Modalix edge silicon.
- **Segment:** QSR, cloud kitchens, retail, hospitality, manufacturing, pharma. Named: Whataburger, Goodwill, Ocean State Job Lot, Mezeh (US); Apparel Group (Gulf); IRCTC, cult.fit, Rebel Foods, Travel Food Services (India); Kitopi (UAE).
- **Pricing:** Per-location SaaS. Free tier up to 10 cameras / 2 checklists / 30 hrs recording; paid from **$40/location/month, 4-camera minimum** (Invincible India deep-dive). Cost drivers are compute + cloud storage. Pricing page (wobot.ai/pricing) now 404 — likely moved to quote-based.
- **Deployment:** Cloud; integrates existing CCTV via NVR/VMS partners (OpenEye, Interface named). Moving toward edge via SiMa.ai.
- **Traction:** **FY25 revenue ₹13.3 Cr (~$1.4M) per MCA filings; 54% 1-yr CAGR; FY23 <₹1 Cr.** Latka's "$11.6M ARR / ~110 people" is almost certainly wrong vs filings (treat as unverified). Profitability undisclosed.
- **Funding:** Titan Capital seed (~2019); $2.5M pre-Series A led by Sequoia India (Aug 2020); Surge (Peak XV) round Oct 2024. Trackers disagree $2.5–5.5M total.
- **Weaknesses:** "Big logos, thin revenue line"; pivoted 2019–20 from food-hygiene tool to horizontal platform; revenue concentrated in footfall-sensitive sectors; dependence on third-party hardware vendors who could build features natively; India is a pilot market, revenue skewed to US/Gulf. ~7 yrs in, still <$2M revenue.
- **Lesson:** horizontal "any-SOP" platform + India home market = slow; the money came from US QSR franchisees.

#### Staqu Technologies — JARVIS (Gurugram)
- **Does:** Audio+video analytics on existing IP cameras: retail (footfall, conversion, staff coverage, queue, SOP, theft), manufacturing safety, hospital (patient fall, hygiene, staff compliance — Aster, Bridge Health named), hospitality, government/police (origin: FRS for UP Police — **[stale]** 2018–20). Also "Jarvis GPT" for retailers (2025).
- **Segment:** Retail chains are the current anchor. Metro Brands (200+ footwear stores): claims 23% store-OPEX reduction, +14% conversion. Rebel Foods kitchen monitoring (Microsoft case study).
- **Pricing:** Not public. One 2026 review cites "~₹8,000/camera/month starting" — looks high; a Capterra listing shows "$45 flat/month". Treat both as unreliable; quote-based, depends on cloud vs on-prem.
- **Deployment:** Cloud primary (Azure), on-prem available; plug-and-play on existing cameras.
- **Traction:** FY25 revenue **₹19.6 Cr (+40.7% from ₹14.0 Cr)**. Claims 200+ active clients, "zero churn" (self-reported, unverified). 2 patents.
- **Funding:** ~$1.44M across 3 rounds (Indian Angel Network etc.) — essentially capital-efficient/bootstrapped.
- **Weaknesses:** Opaque pricing; pivot history (police FRS → enterprise) means civil-liberties baggage on FRS; public "about" page has placeholder zeros for metrics; no public reviews; small capital base for a 7-sector footprint.

#### Awiros (Gurugram)
- **Does:** "Video intelligence OS" + app-store model: third-party and in-house AI apps (ANPR, FRS, PPE, crowd, intrusion, etc.) run on one orchestration layer; targets smart cities, law enforcement, airports, transport, manufacturing, logistics.
- **Pricing:** Not public; platform + per-app licensing (not verified).
- **Deployment:** On-prem GPU servers / edge; also cloud. Site fetch failed (JS-rendered) — customers not verified in this run.
- **Traction:** Revenue ₹10–50 Cr band (FY25, Tracxn); Growjo-style estimates $1–10M.
- **Funding:** $7.75M total; $7M Series A Sept 2022 (Inflexor, Exfinity, Shastra VC, Sprint VC; MeitY grant).
- **Weaknesses:** Government/smart-city tender dependence → long receivables; no new round since 2022; enterprise commercial segment is secondary.

#### Vehant Technologies (Noida)
- **Does:** Hardware+software security: under-vehicle scanners, baggage X-ray, ANPR/traffic enforcement, FRS, and "enterprise video analytics" (PPE, intrusion, crowd) — e.g., CPCL refinery safety analytics (May 2025).
- **Segment:** Aviation, government/smart city (60–65% of tender pipeline), defence, enterprise (hotels, IT parks, refineries).
- **Traction:** FY24 revenue ₹166 Cr (+124%), PAT ₹22 Cr; guided ₹250–300 Cr for FY25 and ₹350 Cr for FY26. **Actual FY25 ≈ ₹100.8 Cr (−39% YoY per Tofler/TheCompanyCheck)** — a severe miss driven by lumpy airport/government orders. IPO "within 12–18 months" promised Jan 2025; no DRHP found as of Nov 2026.
- **Funding:** $9M NCDs from True North (Jan 2025); earlier Mela Ventures etc.
- **Weaknesses:** Tender lumpiness, inventory/receivables, guidance credibility. Enterprise analytics is a side-line to hardware.
- **Lesson:** government-tender video analytics produces spiky, low-multiple revenue; doesn't build a SaaS curve.

#### Videonetics (Kolkata)
- **Does:** Intelligent VMS + analytics (traffic, ANPR, FRS, crowd, BFSI branch/ATM, airports). OMDIA #1 VMS vendor in India (7 yrs), top-10 APAC.
- **Traction:** FY25 revenue **₹78.8 Cr (+29% from ₹61.1 Cr)**; deployed in 150+ cities, 80 airports; AP RTGS CCTV360 ~15,000 cameras unified. BFSI positioning (Mar 2026 PR) built on RBI retention mandates; phased ATM/vault → branch → regional model; edge-in-camera/appliance + central platform.
- **Funding:** ~$26M (Cisco, GenNext Ventures, Tenacity).
- **Weaknesses:** Government/airport-heavy; VMS license model (perpetual + AMC) not SaaS; enterprise retail not core.

#### Uncanny Vision → Eagle Eye Networks India (Bengaluru/Kerala)
- Acquired by Eagle Eye Networks Sept 2021 (**[stale]** event). Became EEN's Bangalore R&D hub; entity revenue ₹33.6 Cr FY25 (largely intra-group R&D billing, not India sales). EEN pricing globally $15–45/camera/month cloud VMS; India enterprise footprint small/unverified.
- **Lesson:** ANPR/edge-analytics startups in India exit as acquihires (~$1.85M raised → acquihire), not as standalone scale businesses.

#### Integration Wizards (IRIS) → SparkCognition/Avathon
- Bootstrapped, profitable from 2014; ~$7M revenue; customers HPCL, Reliance, Heineken, Xerox, Novo Nordisk, JCI. Acquired Mar 2022 (**[stale]**). Parent (now Avathon) has had repeated layoffs; IRIS visibility in India has faded.
- **Lesson:** second India exit via acquihire into an industrial-AI roll-up; founders didn't get to a venture-scale outcome.

#### Pixuate (Bengaluru, est. 2012)
- $1.18M raised ($1M seed 2021, SucSEED). 20+ enterprise customers (highways/tolls with L&T, banks, retail, manufacturing). Revenue not disclosed; no news since 2021 → stagnant.

#### Intozi (Gurugram)
- Bootstrapped (~$85K); revenue <₹10 Cr FY25 but 99% growth; sells on GeM at ₹99K–₹118K per AI video-analytics software license (per server/channel bundle). Telecom, banking, agri, smart city. Low-cost tender player.

#### Tusker AI (Ahmedabad)
- Angel round 2022 only; pivoted to "no-code vision AI" for manufacturing/logistics/construction (defects, productivity, SOP, safety). Pre-scale. "Ameliorate" — no company found under that name.

#### CamCom (Bengaluru)
- Visual inspection/defect detection (vehicles, parts) — not CCTV surveillance analytics. $1.74M raised; revenue ₹10–50 Cr; 113 staff (Sep 2026). Adjacent, not a direct competitor.

#### Agrex AI (Gurugram)
- Retail/bank/warehouse analytics on existing cameras; edge processing; "no FRS, no biometrics, DPDP-compliant"; WhatsApp alerts. **Publishes pricing: ₹800–₹1,200/camera/month; ₹8–12K/month for a 10-camera store**; claims Bata India (+32% conversion), Pantaloons, M&S India; "100+ facilities"; 3–5-day deployment per site via edge device + RTSP. Funding only $407K (Strawberry Fields). Heavy SEO content; traction claims unverified.

#### Netra / Gaist / Zestl / Edgematrix / Vmaxx / Pensieve / Nimble Vision
- Netra (US, Mark Cuban) and Edgematrix (Japan) are not India CCTV players. Gaist, Zestl, Vmaxx, Pensieve: no findable India CCTV-analytics entity. Nimble Vision = water/sewage IoT, not worker safety. **Drop from the competitor set.**

### 1.2 Industrial / worker-safety specialists

#### Ripik.ai (Noida)
- **Does:** Vision-AI "agents" for process plants: material/process/equipment anomaly detection, conveyor, compliance, workforce monitoring. Steel, cement, aluminium, power.
- **Customers:** ArcelorMittal, Hindalco, JSW Steel, Jindal Steel, Hindustan Zinc, Tata Steel, Godrej & Boyce, IMFA, Cimko; Aditya Birla, Vedanta group companies.
- **Traction:** revenue ₹10–50 Cr band FY25 (Latka "$9.1M" unverified). $14.2M raised (Accel, Venture Highway/General Catalyst); **in talks for ₹140–150 Cr from Gaja Capital (Nov 2026, not closed)**.
- **Deployment:** On-prem/edge with own cameras + sensors; project-style, not self-serve.
- **Weakness:** services-heavy integration; each plant a bespoke model; long sales cycle.

#### Detect Technologies (Chennai) — T-Pulse
- Industrial safety video analytics (PPE, zone intrusion, work-at-height) + asset inspection + privacy anonymisation. FY25 revenue **₹51.0 Cr (+41.8%)**; $43.3M raised (Accel, Elevation, Prime; last round Jul 2022). Customers historically Tata Steel, Vedanta, HPCL, Reliance (not re-verified this run).
- **Largest pure-play safety-vision revenue in India**; proof that PSU/large-conglomerate safety budgets pay.

#### Invigilo (Singapore)
- 40+ risk types on existing RTSP/ONVIF cameras; ~200 active sites; construction/O&G/manufacturing/mining/logistics; named Saipem, Hyundai E&C, Keppel, ST Engineering, PUB, Penta-Ocean, Gammon, Nishimatsu; Saudi Aramco SCC approved vendor. Hybrid edge/cloud ("only events leave the site"). Claims 95% recall, 80–90% precision, 60% fewer incidents on one HDB site. ~$0.5M raised (NUS GRIP, BLOCK71, NVIDIA Inception); Latka ~$1.7M ARR (2024). **No India presence listed.** Pricing by sites+cameras, quote-based.

#### Industry.AI
- No verifiable entity found under this name in India. Not verified.

#### Demand-side evidence (worker safety)
- Tata Steel: >10,000 CCTV cameras with AI surveillance across plants; driver-fatigue vision on 8–10K trucks/day; ₹802 Cr safety/environment capex FY26 (vendors unnamed).
- NTPC Sipat Stage-III tender (Sep 2026): AI CCTV for work-at-height, PPE, restricted zones, 420-day project.
- CPCL refinery (Vehant, May 2025).

### 1.3 ATM / BFSI e-surveillance

#### Securens Systems (Navi Mumbai) → CMS Info Systems
- Remote e-surveillance for ATMs/branches (sensors + cameras + central monitoring + two-way audio deterrence). FY25 revenue **₹76.6 Cr (−3.9% YoY)**. **Acquired by CMS Info Systems: EV ₹80 Cr (Jul 2025 → 100% by Mar 2026)** to build CMS's "Vision AI / AIoT remote monitoring" business, claimed to be 2x nearest competitor post-deal.
- Price anchor **[stale]**: founder pitch was ~¼ the ₹30K/month/ATM guard cost → ~₹7,500/ATM/month bundled.
- **Lesson:** ATM e-surveillance is a real, recurring, ~₹80 Cr/yr business, but it's flat and traded at ~1x revenue; value accrues to the cash-logistics incumbent, not to the analytics startup.

#### Hitachi Payment Services
- >₹1,000 Cr revenue FY25; runs ATM networks; e-surveillance is embedded in managed-services contracts (no standalone analytics product verified).

#### SBI (Feb 2025)
- RFP for consultants to design AI-camera + thermal + video-analytics surveillance across **22,685 branches** (+20% growth headroom), single command centre in Mumbai. Largest single BFSI opportunity; will be awarded to SI/consultant → OEM, not to a startup directly.

### 1.4 OEM built-in analytics and telco bundles (the "free analytics" floor)

| Player | What's built in | Price | Note |
|---|---|---|---|
| Hikvision AcuSense | Human/vehicle classification, line-crossing, intrusion, false-alarm filtering on-camera | ₹4,000–₹10,000/camera (Flipkart/IndiaMart) | Zero marginal software cost; **no new sales post-Apr 2026** but massive installed base |
| Dahua WizSense | Same class | ~15% below Hikvision | Same STQC block |
| CP Plus "AI" cameras/NVRs | Human/vehicle, perimeter, face capture on select models | ₹1,500–₹25,000; ~15–25% cheaper than Hikvision | Now the default new-install brand (45% share of IP segment) |
| Airtel Xsafe | Consumer/SOHO cloud CCTV | from ₹119/month | Not enterprise analytics |
| Jio / JioSecure + Jio Bridge | Cloud storage + "vertical video analytics (process compliance, security)" on JioSecure-compatible cameras, India DCs | Not public | App updated Jan 2026; enterprise traction unverified |
| Tata Communications | Managed video analytics platform, 25–50+ pre-built use cases, "Video Analytics Lite App" for retail, drone analytics; Frost & Sullivan 2025 award | Enterprise contracts | Sells to its existing telco enterprise base; SI-style |
| Yotta DRISHTICAM (VSaaS) | Cloud VMS ₹1,800/cam/mo; AI tiers **₹250 (intrusion/loitering) / ₹350 (people count, heatmap, fire, fall) / ₹1,200 (FRS, ANPR, PPE) / ₹3,500 (traffic violations) per unit/month**; storage ₹2.60/GB/mo; PS ₹27K/man-day | Published | Best public India price list found |
| Godrej Security Solutions | ₹1,200 Cr FY25; cloud surveillance, "AI-enabled CCTV", SmartFog | Hardware-led | Channel + brand, not analytics IP |
| Zicom | **Insolvent**: CIRP from Jul 2022 (IDBI petition); ₹17.75 Cr resolution plan approved Sep 2026 vs FY23 loss ₹1,081 Cr | — | Cautionary tale: capital-heavy SI/leasing model collapsed |
| Honeywell / Bosch / Milestone / Genetec India | Enterprise VMS + partner analytics via SIs | Perpetual licenses | Not verified this run (search budget) |

### 1.5 Residential societies
- MyGate / NoBrokerHood (40,000+ complexes) are visitor/gate SaaS; **no first-party camera-analytics product found** for either. NoBrokerHood markets "integrates with smart CCTV / FRS biometrics / ANPR boom barriers" via partners. Gatekeeper/ADDA: not verified. Rest of World (2023) flagged bias concerns in gate apps — reputational risk for FRS in this segment.
- Camera analytics in societies today = OEM AcuSense-style alerts on the NVR, or ANPR at the boom barrier sold by integrators. No SaaS layer with pricing power is visible.

### 1.6 Retail shelf / merchandising (adjacent, not CCTV)
- **Infilect** (InfiViz, Bengaluru): FY25 revenue ₹17.8 Cr (+5.4%) — growth stalled; $3.06M raised (Mela Ventures, Lowe's Labs). Image recognition from phone/store audits for CPG.
- **ParallelDots**: $6.5M raised; revenue ₹10–50 Cr band; phone-image shelf recognition.
- Both monetise CPG brands' trade-marketing budgets, not retailers' CCTV. Relevant only as proof that CPG pays for store-level vision data.

---

## 2. Global comparables (pitch benchmarks)

| Company | Model | Pricing | Traction / funding | What worked / caveat |
|---|---|---|---|---|
| **Verkada** | Proprietary cameras + cloud, license per device | ~$199–$1,799/camera/yr license + $500–$2,000 cameras | 2025 revenue ~$806M; ARR >$400M (Nov 2025); $1B annualised bookings; ~30–31K customers; $5.8B valuation (CapitalG, Dec 2025); $744M raised; 30% YoY growth; Dubai hub 2026, **no India office** | Hardware-bundled → high ACV, channel-friendly; India blocked by import duties/STQC and price |
| **Rhombus** | Own cameras + cloud | Cameras $399–$3,299; license $149/yr (Pro, no AI) to $649/yr (Enterprise w/ AI) | ~$38.7M ARR (2024); $112.5M raised | Same playbook as Verkada, SMB/mid-market |
| **Spot AI** | Camera-agnostic (existing IP/analog) + on-site IVR + cloud | ~$99/camera/month reference; $1.5–5K install/location | $22M Series A (Nov 2025 per snippet; earlier $40M+ total) | "Reuse your cameras" wedge; agentic video; closest analogue to an India brownfield play |
| **Lumana** | VLM/agentic analytics on any camera | Quote | $40M Series A (Jul–Aug 2025, Wing); $64M total; "1B images/day" | Shows VLM-based natural-language video search is fundable; late entrant can win on AI quality |
| **Coram AI** | Free NDAA cameras + Coram Point box + cloud license (1/3/5/10-yr) | Quote; by locations, camera type, retention | $13.8M Series A (Jan 2025, Battery); $30M total | "Free cameras" to subsidise long software contracts |
| **Ambient.ai** | Enterprise physical-security AI on existing cameras (SOC) | Enterprise | $146M total; $74M round Apr 2025 | Large-enterprise GSOC; long sales cycle |
| **Hakimo** | "AI Operator" remote guarding on existing cameras/badge readers | Per-site monitoring (replaces guards) | $10.5M Series A (Mar 2025), $20.5M total; 100+ clients; customers tripled | **Guard-replacement economics** = clearest WTP globally |
| **Eagle Eye Networks** | Cloud VMS, camera-agnostic | $15–45/camera/month | ~$113–116M revenue; $175M raised; Bangalore R&D via Uncanny Vision; remote video monitoring launched Oct 2025 | Cloud VMS first, analytics second |

**Price comparison:** US cloud VMS+AI sits at **$15–99/camera/month** (₹1,300–8,500). India analytics SaaS clears at **₹500–1,200/camera/month ($6–14)**, i.e., 5–10x lower; India cloud VMS without analytics at ₹150–800. Indian ACVs per site are therefore $100–300/month, which is why nobody in India has crossed ₹100 Cr on pure analytics SaaS.

---

## 3. Answers to the five questions

### Q1. Use cases with proven willingness to pay in India (ranked, with evidence)

1. **Industrial worker safety / PPE / zone / work-at-height in heavy industry (steel, cement, power, refining, mining).** Evidence: Detect Technologies ₹51 Cr FY25 (+42%); Ripik ₹10–50 Cr with JSW/Hindalco/Tata Steel/Hindustan Zinc and a ₹150 Cr PE round in discussion; Tata Steel 10,000+ AI cameras; NTPC and CPCL tenders. Budget line = safety capex/ESG, buyer = plant head/CSO, deal size ₹25L–₹5 Cr per plant. Highest ACV; sticky; but project-shaped.
2. **ATM / branch e-surveillance and remote monitoring (BFSI).** Evidence: Securens ₹77 Cr recurring, acquired by CMS for ₹80 Cr to build Vision AI; Hitachi Payment embeds it; SBI 22,685-branch AI surveillance RFP; RBI retention mandates; Videonetics BFSI push. WTP is guard-replacement arithmetic (~₹7.5K vs ₹30K/ATM/month **[stale anchor]**). Mature, price-compressed, SI-controlled.
3. **QSR / cloud-kitchen hygiene & SOP compliance.** Evidence: Rebel Foods (Wobot, then Staqu), Jubilant FoodWorks "expanding AI-enabled surveillance to strengthen compliance" (Q2 FY27), Travel Food Services, cult.fit. Buyer = COO/food-safety head; driven by FSSAI audits + brand risk. But Wobot's India revenue is small — Indian QSR pays, just at ₹500–1,000/camera.
4. **Organised retail store ops (footfall → conversion, staff coverage, queue, theft).** Evidence: Metro Brands 200+ stores on JARVIS (23% OPEX claim), Bata/Pantaloons/M&S India on Agrex (claims), asmag "retail is fastest-adopting; jewellery and apparel chains". Price ₹800–1,200/camera/month. Real but each chain is a ₹20–80L/yr account.
5. **Government/smart-city/airport analytics (ANPR, FRS, crowd).** Largest rupee volume (Videonetics ₹79 Cr, Vehant ₹100–166 Cr, Awiros) but tender-driven, lumpy, low multiple, and not "enterprise".
6. **Hospitals (patient fall, hygiene, staff compliance)** — early; Staqu names Aster, Bridge Health; IndoAI/FlowLinks selling on-device fall detection. WTP unproven at scale.
7. **Warehouses/logistics (dock, DEPS/damage, forklift safety)** — vendors (Agrex) claim 100+ facilities; no named 3PL/e-com deployment found. Unproven publicly.
8. **Education campuses** — CBSE mandate drives camera sales, not analytics; buyers want cheapest compliant recording. Low WTP.
9. **Residential societies** — zero visible analytics SaaS; OEM alerts suffice. Lowest WTP.
10. **Malls, hospitality** — footfall vendors exist (Staqu mall footfall content) but no public traction; not verified this run.

### Q2. Price points in India vs US

| Layer | India (per camera/month) | US |
|---|---|---|
| Cloud recording only (telco/consumer) | ₹120–300 (Airtel Xsafe ₹119; ~₹3,500/yr) | $10–20 |
| Enterprise cloud VMS, 7-day retention | ~₹500 (asmag); Yotta ₹1,800 | $15–45 (EEN) |
| AI analytics add-on, basic (intrusion, loitering, count, heatmap) | **₹250–350** (Yotta), ₹800–850 (asmag mid), ₹800–1,200 (Agrex retail) | Rhombus Enterprise license ≈ $12–54/mo equivalent |
| AI analytics, advanced (FRS, ANPR, PPE) | ₹1,200 (Yotta); ₹500–2,000 range quoted broadly | $50–99 (Spot AI ~$99) |
| Specialised (traffic violations) | ₹3,500 (Yotta) | n/a |
| Per-location SaaS (QSR) | Wobot $40/location/month (4+ cameras) ≈ ₹850/camera | same product, US-priced |
| On-prem perpetual license (tenders) | Intozi ₹99K–1.9L per software license on GeM; Rhombus/Milestone-style $50–200/cam perpetual | — |
| Setup | Edge box + 3–5 days install per site (Agrex); Yotta PS ₹27K/man-day; US install $1.5–5K/location | — |

Takeaways: India analytics SaaS lands at **$3–15/camera/month**, roughly 1/7 of US. Most Indian vendors hide pricing (Staqu, Awiros, Vehant, Jio, Tata Comms); the few who publish (Yotta, Agrex, Wobot) cluster at ₹250–1,200. Setup/PS fees and edge hardware (₹40–80K per 8–16-channel GPU box, vendor-quoted ranges; not independently verified) are often where the margin is.

### Q3. Deployment reality
- **Brownfield dominates.** Every credible vendor (Staqu, Agrex, Invigilo, Spot AI, Wobot, Videonetics) sells "works with cameras you already have" via RTSP/ONVIF or NVR integration. Installed base is majority Hikvision/Dahua analog-over-coax DVRs and low-bitrate IP; analytics needs IP streams ≥1080p, so analog estates need encoders or camera swaps. Post-STQC, new installs are CP Plus/Prama/Matrix — ONVIF support is uneven on budget models.
- **Bandwidth.** Entry cloud plans run at 70–90 kbps/camera (asmag) — fine for clips, useless for analytics. Continuous upload of 16 cameras at 2 Mbps = 32 Mbps sustained upstream, which most Indian SME broadband (asymmetric; JioFiber/Airtel 100–300 Mbps down, far less reliable up) and factory links cannot guarantee. Hence the consensus **hybrid**: edge inference on-site (Jetson/Intel/SiMa box or in-camera NPU), only events/clips to cloud ("only events leave the site" — Invigilo). Pure cloud works only for ≤4-camera QSR/retail with clip-based SOP checks (Wobot's model).
- **Edge box economics.** 10–50 ms edge latency vs 100–200 ms cloud; edge is higher upfront, lower opex. The Indian "cheap edge box" is typically a Jetson Orin Nano/NX-class or RK3588 appliance handling 8–16 streams of light models; GPU servers for 50–200 streams. Yotta's ₹250–350/unit tiers imply cloud inference on event clips, not full-frame streaming.
- **Data residency / DPDP.** Vendors increasingly market "no FRS, no biometrics" (Agrex) and "on-device processing" (IndoAI). India-DC cloud (Jio, Yotta) is a selling point for BFSI/government.
- **Who installs.** Local CCTV integrators (the Hikvision/CP Plus dealer network) control the site; successful vendors (Securens, Agrex, Yotta) either own field ops or ride a telco/SI. No Indian analytics startup has a self-serve install motion.

### Q4. Whitespace hypotheses (where incumbents fail and why)

1. **Hybrid edge-first analytics for mid-market factories & warehouses (50–300 cameras) at ₹300–600/camera/month, self-installed on existing NVRs.** Detect/Ripik/Vehant sell ₹25L+ projects to conglomerates; Agrex/Staqu are cloud-leaning; OEM AcuSense gives only human/vehicle. The 50,000+ mid-size plants, 3PL warehouses and cold chains have no productised option between "free NVR alerts" and "₹50L project". Why incumbents fail: services-heavy delivery, no channel into Tier-2 industrial clusters, bandwidth assumptions.
2. **Guard-replacement remote monitoring (Hakimo-style) for societies, schools, warehouses, construction sites, small banks.** India's biggest security opex is guards (₹15–30K/guard/month). Securens proved the math at ATMs; CMS now owns that; nobody offers an AI-operator + talk-down + dispatch service for the other verticals. Why incumbents fail: Securens is ATM-only and acquired; MyGate/NoBrokerHood monetise visitor flows, not cameras; guard companies lack tech. Caution: needs 24x7 ops and liability model.
3. **STQC-transition analytics layer:** a camera-agnostic analytics/VMS that treats legacy Hikvision/Dahua + new CP Plus/Prama/Matrix estates as one fleet, sold through the dealer channel that is losing Hikvision margin and needs a new attach product. Why incumbents fail: OEM analytics are brand-locked; Milestone/Genetec are too expensive; Indian SaaS vendors don't sell through dealers.
4. **QSR/food-service compliance priced for India** (₹300–500/camera, WhatsApp-native, Hindi UI, FSSAI audit packs). Wobot built the product but priced/sold it for the US; Staqu does it as one of seven verticals. Jubilant, Devyani, Westlife, Rebel, Zomato Hyperpure kitchens are a few thousand sites with real audit pain.
5. **Hospital ward safety (falls, restraint, hand-hygiene) with on-device privacy.** Only Staqu (one vertical) and tiny IndoAI/FlowLinks; NABH accreditation and nurse shortages create pull. Unproven WTP — treat as second bet.
6. **VLM-based natural-language forensic search for Indian SMEs** (Lumana/Spot AI feature) on existing NVR footage — nobody in India offers it; cheap to build on open VLMs; monetises the "find what happened" moment rather than always-on alerts.

Anti-whitespace (avoid): government/smart-city tenders (lumpy, 60-day+ receivables, L1 pricing — Vehant/Intozi), residential FRS (bias backlash), shelf analytics (Infilect flat), ATM e-surveillance (consolidated into CMS/Hitachi).

### Q5. Failure / pivot stories and lessons

| Story | What happened | Lesson |
|---|---|---|
| Wobot.ai | 2017 food-hygiene tool → 2020 horizontal platform (Sequoia $2.5M) → US QSR logos; FY25 ₹13.3 Cr after 7 yrs; pricing page pulled | Horizontal "any checklist" dilutes; India WTP forced a US pivot; a thin product on cloud compute has thin margins at ₹/camera pricing |
| Vehant | Guided ₹250–300 Cr FY25, delivered ~₹101 Cr (−39%); IPO slipped; True North NCDs | Tender-dependent hardware+analytics is not a SaaS story; don't anchor a pitch on government pipeline |
| Securens → CMS | 14 yrs to ₹77 Cr, flat, sold for ₹80 Cr (~1x) | Monitoring-as-a-service wins recurring revenue but gets commoditised; strategic value accrued to the cash-logistics incumbent |
| Zicom | Listed SI with leasing/annuity model; CIRP 2022; ₹1,081 Cr FY23 loss; ₹17.75 Cr resolution 2026 | Capital-heavy hardware leasing + receivables kills security companies; stay asset-light |
| Uncanny Vision → EEN; Integration Wizards → SparkCognition | Both acquihired 2021–22 for small sums after ~$2M raised; parent (Avathon) in repeated layoffs | India CV startups exit as R&D centres unless they own a vertical and recurring revenue |
| Staqu | Started as police FRS (UP Police) → now retail/hospital ops | Government FRS is reputationally costly and non-recurring; enterprise ops analytics is where the renewals are |
| Infilect | FY25 +5% after a decade; $3M raised | CPG trade-marketing budgets cap shelf-vision growth; phone-image audits are a services business |
| Pixuate / Intozi / Tusker | Sub-scale for 5–14 yrs; GeM L1 pricing; no follow-on rounds | Without a vertical wedge and a channel, Indian video-analytics startups plateau at ₹5–20 Cr |
| Hikvision/Dahua | Lost right to sell new networked cameras in India (Apr 2026) | Platform risk is regulatory as well as technical; be camera-agnostic and STQC-aware |

---

## 4. Competitor table (compact)

| Company | Segment | Model | Pricing clue | Traction | Funding | Weakness |
|---|---|---|---|---|---|---|
| Wobot.ai | QSR/retail/hospitality SOP | Cloud SaaS on existing CCTV (edge via SiMa coming) | $40/location/mo, 4-cam min; free tier | FY25 ₹13.3 Cr; Whataburger, Goodwill, Rebel Foods, IRCTC | ~$2.5–5.5M (Titan, Peak XV/Surge) | Thin revenue, US-dependent, pricing hidden |
| Staqu (JARVIS) | Retail, hospital, mfg, QSR | Cloud (Azure)/on-prem, existing cams | Quote; claims ~₹8K/cam/mo (dubious) | FY25 ₹19.6 Cr (+41%); Metro Brands 200+ stores; 200+ clients | ~$1.4M | Opaque pricing, FRS legacy, thin capital |
| Awiros | Smart city, airports, mfg | Video-AI OS/app-store, on-prem/edge | Platform + per-app | ₹10–50 Cr | $7.75M (Series A 2022) | Tender-led, no round since 2022 |
| Vehant | Aviation, gov, enterprise | HW + analytics, on-prem | Tender | FY24 ₹166 Cr → FY25 ~₹101 Cr | $9M NCD True North | −39% miss, IPO slipped |
| Videonetics | Gov, airports, BFSI | VMS + analytics, on-prem/edge | Perpetual + AMC | FY25 ₹78.8 Cr; 80 airports, 15K-cam AP project | ~$26M (Cisco etc.) | Gov-heavy, not SaaS |
| Detect Tech (T-Pulse) | Industrial safety | Edge/cloud, projects | ₹25L+ projects | FY25 ₹51 Cr (+42%) | $43M (Accel, Elevation) | No round since 2022; services-heavy |
| Ripik.ai | Process plants | On-prem vision + sensors | Project | ₹10–50 Cr; JSW, Hindalco, Tata Steel | $14M + ₹150 Cr Gaja (talks) | Bespoke per plant |
| Invigilo (SG) | Construction/O&G safety | Hybrid edge/cloud on RTSP/ONVIF | Quote by sites+cams | ~200 sites; Aramco-approved | ~$0.5M | No India presence |
| Securens → CMS | ATM/branch e-surveillance | Sensors+cams+central monitoring | ~₹7.5K/ATM/mo [stale] | FY25 ₹77 Cr flat | Acquired ₹80 Cr EV | Commoditised, now captive |
| Agrex AI | Retail, bank, warehouse | Edge box + existing cams | ₹800–1,200/cam/mo published | Claims Bata, Pantaloons, M&S; 100+ sites | $0.4M | Claims unverified, SEO-heavy |
| Yotta DRISHTICAM | VSaaS horizontal | Cloud VMS + AI tiers | ₹250/350/1,200/3,500 per unit/mo | — | Hiranandani-backed DC | Generic |
| Tata Comms / Jio | Enterprise managed video | Telco-bundled cloud+edge | Enterprise contract | F&S 2025 award; JioSecure app | Corporate | SI-style, slow |
| CP Plus / Hikvision / Dahua | OEM built-in | On-camera NPU | ₹1,500–10,000/camera, no fee | CP Plus 45% IP share post-STQC | Listed/corporate | Brand-locked, basic analytics |
| Intozi / Pixuate / Tusker / CamCom | Niche/long-tail | Mixed | GeM ₹99K–1.9L licenses | <₹10–50 Cr | <$2M each | Sub-scale |
| MyGate / NoBrokerHood | Residential | Gate SaaS; CCTV via partners | n/a | 40K+ societies | Well-funded | No camera analytics product |
| Verkada / Rhombus / Spot AI / Lumana / Coram / Ambient / Hakimo / EEN | Global benchmarks | See §2 | $15–99/cam/mo | Verkada $806M rev, $5.8B val | $20M–$744M | Not in India |

---

## 5. Best sources (2025–2026 unless flagged)
1. https://theinvincibleindia.in/wobot-ai-deep-dive/ — Wobot FY25 ₹13.3 Cr, pricing, pivot
2. https://cofacto.ai/blogs/who-will-capture-indias-cctv-and-ai-surveillance-market-71190cdf — market, STQC impact, CP Plus share, value-chain multiples (Aug 2026)
3. https://cybersecuritynews.com/india-ban-cctv-products/ — STQC / Hikvision-Dahua block (Apr 2026)
4. https://drishticam.ai/plans-and-pricing/ — only full public India AI-analytics price list
5. https://cctvwiki.com/en/unlocking-value-a-deep-dive-into-indias-cloud-based-video-surveillance-pricing-tiers/ (mirror of asmag) — ₹300/500/850 tiers, bitrates, segment adoption
6. https://www.agrexai.com/what-is-retail-video-analytics/ — ₹800–1,200/cam/mo retail, named chains
7. https://www.marketscreener.com/news/cms-info-systems-limited-agreed-to-acquire-securens-systems-pvt-ltd-for-an-enterprise-value-of-inr-ce7c5cd3da8cf223 and https://www.whalesbook.com/news/English/tech/CMS-Info-Systems-Completes-100percent-Securens-Acquisition-Boosts-Vision-AI/69aee1a06431e3e2859d0412 — Securens ₹77 Cr, ₹80 Cr EV
8. https://www.securitytoday.in/sbi-to-go-hi-tech-with-ai-enabled-camera-surveillance-of-its-branches/ — SBI 22,685-branch AI surveillance (Feb 2025)
9. https://www.tradingview.com/news/moodys:9946599cb4c53:0-tata-steel-expands-ai-surveillance-remote-operations-for-workplace-safety/ — Tata Steel 10,000+ AI cameras
10. https://smestreet.in/tender-news/ntpc-invites-tender-for-ai-based-cctv-workplace-safety-monitoring-system-12501307 — NTPC AI-CCTV safety tender (2026)
11. https://inc42.com/company/staqu/ ; https://inc42.com/company/videonetics/ ; https://inc42.com/company/detect-technologies/ ; https://inc42.com/company/securens-systems/financials/profit-loss/ — FY25 revenue figures
12. https://www.thecompanycheck.com/company/vehant-technologies-private-limited/U74999DL2005PTC139427 — Vehant FY25 ₹100.8 Cr (−39%); https://www.outlookbusiness.com/corporate/vehant-technologies-fy24-revenue-up-124-percent-to-rs-166-crore-company-gives-growth-guidance-of-rs-250-300-crore — FY24 guidance
13. https://www.cxodigitalpulse.com/ripik-ai-in-talks-to-raise-up-to-%E2%82%B9150-crore-from-gaja-capital/ — Ripik ₹150 Cr talks (Nov 2026)
14. https://www.invigilo.ai/ — Invigilo customers, hybrid deployment, accuracy
15. https://www.freepressjournal.in/mumbai/nclt-approves-1775-crore-resolution-plan-for-zicom-ending-insolvency-proceedings — Zicom insolvency
16. https://www.cnbc.com/2025/12/03/verkada-capitalg-valuation-security.html ; https://getsafeandsound.com/blog/spot-ai-pricing/ ; https://www.rhombus.com/files/rhombus-price-sheet.pdf ; https://pulse2.com/lumana-40-million-series-a-raised-for-transforming-video-security-with-ai/ ; https://pulse2.com/hakimo-10-5-million-raised-for-physical-security-monitoring-ai-agent-company/ ; https://www.coram.ai/pricing — global benchmarks
17. https://www.videonetics.ai/press-release/bfsi-security-moves-to-ai-driven-video-infrastructure — RBI mandates, BFSI phasing (Mar 2026)
18. https://news.microsoft.com/en-in/features/kitchens-in-the-cloud-ai-is-restoring-consumer-trust-in-the-food-delivery-business/ — Rebel Foods on Staqu/Azure; https://www.medianama.com/2026/11/223-q2fy27-jubilant-foodworks-machine-learning-dominos-price/ — Jubilant expanding AI surveillance

## 6. Gaps / not verified (search budget hit)
- Awiros named customers (site is JS-rendered); Honeywell/Bosch/Milestone/Genetec India share; MyGate/Gatekeeper/ADDA camera roadmaps; mall footfall deployments (Phoenix/DLF/Nexus); Industry.AI identity; Vehant FY25 loss line; Staqu FY25 profit/loss; Invigilo India ops; Verkada India reseller presence; edge-box street prices in India.
