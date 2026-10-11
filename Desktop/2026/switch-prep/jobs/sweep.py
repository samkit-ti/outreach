import json,sys,urllib.request,re
def get(u):
    req=urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'})
    return urllib.request.urlopen(req,timeout=25).read().decode()
TITLE=re.compile(r'(software engineer|ai engineer|applied ai|machine learning|ml engineer|forward deployed|research engineer|member of technical staff|backend engineer|full[- ]stack|platform engineer|solutions engineer|deployment)',re.I)
EXCL=re.compile(r'(senior|staff|principal|lead|director|manager|head of|intern|new grad|graduate|vp|architect|distinguished|sr\.|sr )',re.I)
LOC=re.compile(r'(london|uk|united kingdom|amsterdam|netherlands|berlin|munich|germany|paris|france|zurich|switzerland|dublin|ireland|stockholm|remote|emea|europe|global|anywhere|worldwide|india)',re.I)
for spec in sys.argv[1:]:
    ats,slug=spec.split(':')
    try:
        if ats=='gh':
            d=json.loads(get(f'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs'))
            rows=[(j['title'],j['location']['name'],j['absolute_url']) for j in d['jobs']]
        elif ats=='ashby':
            d=json.loads(get(f'https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true'))
            rows=[(j['title'],j['location']+(' [REMOTE]' if j.get('isRemote') else ''),j['jobUrl']+(' | '+(j.get('compensation') or {}).get('scrapeableCompensationSalarySummary','') if (j.get('compensation') or {}).get('scrapeableCompensationSalarySummary') else '')) for j in d['jobs']]
        elif ats=='lever':
            d=json.loads(get(f'https://api.lever.co/v0/postings/{slug}?mode=json'))
            rows=[(j['text'],j['categories'].get('location',''),j['hostedUrl']) for j in d]
        print(f'=== {spec}: {len(rows)} total')
        for t,l,u in rows:
            if TITLE.search(t) and not EXCL.search(t) and LOC.search(l): print('  ',t,'|',l,'|',u)
    except Exception as e:
        print(f'=== {spec}: ERR {str(e)[:80]}')
