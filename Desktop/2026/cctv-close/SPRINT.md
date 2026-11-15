# CCTV analytics: 2-week LOI sprint (side project, no Trilogy network)

Goal: one signed Letter of Intent for a paid pilot of edge/VLM video analytics on a site's existing cameras.
Budget: 14 days, ~20 working hours total. Close bar: written commitment, cash later.
Decision made 2026-11-15. Market context: ../market-research-india-cctv-ai-video-analytics.md (section 7).

## The one idea that makes 2 weeks possible

Do not install anything. Sell a **free 48-hour footage audit**: the prospect exports 24 h of footage from
2–3 cameras (NVR → pendrive/Drive), you return (a) a searchable timeline ("white truck at dock after 9 pm")
and (b) a one-page findings report. The price of the free audit is a pre-drafted LOI they sign if the
audit is useful. This removes the three things that kill Indian CCTV pilots: site visit, RTSP/NVR access,
and a procurement conversation before value is shown.

## Who to call, in order (owner decides same week)

1. **Your own network first** (day 1, 1 hour): IIT-J batchmates / school friends whose families run a
   factory, warehouse, cold storage, retail chain, hospital, or petrol pumps. Five WhatsApp messages.
   This is the single fastest LOI in India. Warm > everything below.
2. **Owner-run warehouses / 3PL / cold storage** in one belt (Ahmedabad assumption: Aslali–Bavla NH-8,
   Changodar, Sanand; Mumbai: Bhiwandi; NCR: Manesar/Kundli). Pain: pilferage, dock idle time, guards
   asleep, after-hours movement. 20–80 cameras. Owner or GM signs.
3. **MSME factories with safety exposure** (pharma/chemical GIDC estates Vatva, Naroda, Ankleshwar;
   ceramics Morbi). Pain: PPE, restricted zones, Factories Act inspections. Owner signs.
4. **Regional retail / jewellery chains, 5–50 stores**. Pain: theft, opening/closing compliance,
   footfall. Smaller ticket, fast decision.
5. **Backup "client": a CP Plus / Prama-Hikvision dealer** with 50+ installed sites. LOI = "we will pilot
   at 2 customer sites and resell at 25% margin". Dealers answer the phone the same day.

Skip for this sprint: government, schools (children + DPDP), housing societies (committee decisions),
large corporates (procurement > 2 weeks).

## Funnel to plan for (cold, India SMB, free offer)

| Stage | Count | Hours |
|---|---|---|
| Names + phone numbers | 40 | 3 |
| Real conversations (call/WhatsApp) | 12 | 3 |
| Footage received | 4 | 1 |
| Audits delivered + walkthrough calls | 3–4 | 6 |
| LOIs signed | 1–2 | 1 |

## Schedule (20 hours)

**Days 1–2 (4 h):** send 5 network messages; finalise LOI (template below); write the one-page offer;
set up a WhatsApp Business profile + Google Drive upload link for footage.
**Days 3–4 (5 h):** build the audit pipeline (spec below) on one public CCTV clip; record a 90-second
screen demo.
**Days 5–7 (4 h):** build the 40-name list; 20 calls + 20 WhatsApps; book footage hand-offs.
**Days 8–11 (5 h):** run audits on received footage; 30-minute walkthrough call each; hand over LOI.
**Days 12–14 (2 h):** chase signatures; collect the second LOI; log learnings.

## Audit pipeline (build in ~5 hours, your stack)

1. `ffmpeg` → 1 fps frames, dedupe near-identical frames (hash).
2. YOLO11n for person/vehicle events; group into clips (start/end, zone).
3. Caption each event clip with a VLM (Gemini Flash or Qwen2.5-VL 7B); store caption + timestamp.
4. BM25/embedding search over captions; Streamlit page: text box → ranked clips with thumbnails.
5. Report generator: after-hours person events, dock/vehicle dwell per hour, PPE misses (Roboflow
   Universe hard-hat/vest model), top 10 anomalies with thumbnails → one-page PDF.
Footage formats: Hikvision exports .mp4 via its player; Dahua/CP Plus `.dav` → convert with ffmpeg.
Run on your own hardware/accounts only (not Trilogy's). Delete footage 30 days after the audit; say so in writing.

## Sourcing the 40 names (3 hours)

- IndiaMART / JustDial: "warehouse", "cold storage", "logistics park", "pharma manufacturer" + city.
- Google Maps: pan the industrial estate, list units with a phone number; call the landline, ask for owner/GM.
- LinkedIn (free): titles Owner / Director / Plant Head / Warehouse Manager within 50 km; connect with a
  one-line note, then move to WhatsApp.
- GIDC estate industrial associations publish member lists (Vatva, Naroda, Sanand, Changodar).
- CP Plus dealer locator (cpplusworld.com) and Prama partner locator for the dealer backup.

## Scripts

**WhatsApp (first touch):**
> Hi <name>, I'm Samkit, I build AI for CCTV. Free 48-hour audit of your existing cameras: send me
> 24 hours of footage from 2 cameras, I'll return a searchable timeline (type "truck at gate after
> 9 pm", get the clip) and a one-page report on after-hours movement, idle time and safety misses.
> No install, no cost. Want it for your <warehouse/plant>?

**Call (60 seconds):**
"I'm calling for the owner or plant head. I turn the CCTV you already have into answers: you type what
you want to find and get the clip in seconds, and you get a daily 7 am summary on WhatsApp. I'm doing
free 48-hour audits for 5 sites in <estate> this month. Can your team export one day of footage from
two cameras? I'll send a Drive link."

**Objections:**
- "We already have Hikvision/CP Plus alarms" → "Those fire in real time. This is search and a daily
  summary over footage you already store. Different job, same cameras."
- "Privacy" → "Processed on my machine, deleted within 30 days, written in the letter. Full on-prem
  box option if we go ahead."
- "Price?" → "Zero for the audit. The letter says what you'd pay only if the audit proves useful."

## LOI template (one page, non-binding except confidentiality)

> **Letter of Intent — Paid Pilot of Video Analytics**
> Between: <Company>, <address> ("Company") and Samkit Shah ("Provider"). Date: <date>.
> 1. **Purpose.** Company intends to run a 14-day pilot of Provider's video analytics on <N> existing
>    cameras at <site>, using footage/stream access Company provides. The pilot is free of charge.
> 2. **Success criteria** (agreed before start): e.g. ≥80% of after-hours person events in the test
>    period are found by natural-language search; daily summary delivered by 07:00 on each pilot day;
>    <one site-specific metric, e.g. dock idle time reported per shift>.
> 3. **Intent on success.** If the criteria are met, Company intends to subscribe for 12 months at
>    ₹<500>/camera/month for <N≥20> cameras plus a one-time on-site unit fee of ₹<40,000>, under a
>    contract to be mutually agreed by <date + 30 days>.
> 4. **Data handling.** Footage is used only for the pilot, stored on Provider's or Company's
>    equipment, not shared, and deleted within 30 days after the pilot. Both parties keep the
>    other's information confidential.
> 5. **Nature.** Clauses 1–3 express intent and are not binding. Clause 4 is binding.
> 6. **Validity.** This letter is preliminary; the parties will refine or withdraw it by <date + 45 days>.
> Signed: ____________ (Company, name/title)    ____________ (Provider)

## Pricing anchors (from the market study)

| Item | Anchor |
|---|---|
| Subscription | ₹400–600 per camera per month |
| Edge unit (10–16 cams) | ₹40–60k one-time |
| Minimum | 20 cameras, 12 months |
| Dealer margin (backup path) | 20–30% |

## Learnings log

| Date | Who | Outcome | What I learned |
|---|---|---|---|
| | | | |
