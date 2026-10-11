import json, glob, re, html, sys, os
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
rows = []
for f in sorted(glob.glob(os.path.join(HERE, "*.json"))):
    try:
        data = json.load(open(f))
    except Exception as e:
        print("BAD JSON", f, e, file=sys.stderr); continue
    if isinstance(data, dict):
        data = data.get("rows") or data.get("jobs") or list(data.values())[0]
    for r in data:
        if not isinstance(r, dict): continue
        r.setdefault("bucket", os.path.basename(f).replace(".json",""))
        rows.append(r)

# normalise + dedupe
seen = {}
def key(r):
    u = (r.get("url") or "").strip().lower().rstrip("/")
    return u or ((r.get("company") or "").lower().strip(), (r.get("role") or "").lower().strip())
for r in rows:
    k = key(r)
    try: r["fit_score"] = int(float(r.get("fit_score") or 0))
    except: r["fit_score"] = 0
    for fld in ["company","role","url","location","work_mode","yoe_required","comp_estimate","comp_source","comp_confidence","visa_path","fit_notes","status","notes","bucket"]:
        v = r.get(fld)
        r[fld] = "" if v is None else str(v).strip()
    if k in seen:
        old = seen[k]
        if r["fit_score"] > old["fit_score"] or (len(r["fit_notes"]) > len(old["fit_notes"])): seen[k] = r
    else:
        seen[k] = r
rows = list(seen.values())
rows.sort(key=lambda r: (-r["fit_score"], r["company"].lower()))

BUCKETS = {
 "india_ai": "India · AI/ML",
 "fde_startup": "FDE · AI startups",
 "india_sde": "India · SDE2",
 "quant": "Quant",
 "intl_uk_eu_us": "Intl · UK/EU/US",
 "intl_apac_me": "Intl · SG/UAE/AU",
}
counts = {b: sum(1 for r in rows if r["bucket"]==b) for b in BUCKETS}
verified = sum(1 for r in rows if r["status"].startswith("verified"))
today = date.today().isoformat()

tpl = open(os.path.join(HERE, "template.html")).read()
out = tpl.replace("/*__DATA__*/", json.dumps(rows, ensure_ascii=False)) \
         .replace("__TOTAL__", str(len(rows))).replace("__VERIFIED__", str(verified)) \
         .replace("__DATE__", today).replace("/*__BUCKETS__*/", json.dumps(BUCKETS, ensure_ascii=False))
for b,n in counts.items(): out = out.replace(f"__N_{b}__", str(n))
open(os.path.join(HERE, "switch-board.html"), "w").write(out)
print(f"rows={len(rows)} verified={verified} by bucket={counts}")
