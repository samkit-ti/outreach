import json,sys,re,html,urllib.request
def get(u):
    req=urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'})
    return urllib.request.urlopen(req,timeout=30).read().decode()
def strip(h):
    h=re.sub(r'<br\s*/?>|</p>|</li>|</div>','\n',h); h=re.sub(r'<[^>]+>','',h); return html.unescape(h)
def excerpt(txt,keys=('year','experience','salary','£','€','$','CHF','compensation','visa','sponsor','relocat','remote','hybrid','clearance','PhD','Base')):
    out=[]
    for line in txt.split('\n'):
        l=line.strip()
        if l and any(k.lower() in l.lower() for k in keys) and len(l)<400: out.append(l)
    return out
kind,a,b=sys.argv[1],sys.argv[2],sys.argv[3] if len(sys.argv)>3 else None
if kind=='gh':
    d=json.loads(get(f'https://boards-api.greenhouse.io/v1/boards/{a}/jobs/{b}'))
    print('##',d['title'],'|',d['location']['name'],'|',d['absolute_url'],'| updated',d.get('updated_at'))
    for l in excerpt(strip(d['content'])): print(' -',l)
elif kind=='ashby':
    d=json.loads(get(f'https://api.ashbyhq.com/posting-api/job-board/{a}?includeCompensation=true'))
    for j in d['jobs']:
        if j['id']==b:
            print('##',j['title'],'|',j['location'],'|',j['jobUrl'],'| published',j.get('publishedAt'))
            print(' comp:',json.dumps(j.get('compensation'))[:600])
            for l in excerpt(j.get('descriptionPlain','')): print(' -',l)
elif kind=='lever':
    d=json.loads(get(f'https://api.lever.co/v0/postings/{a}/{b}'))
    print('##',d['text'],'|',d['categories'].get('location'),'|',d['hostedUrl'])
    txt=d.get('descriptionPlain','')+'\n'+'\n'.join(l.get('text','')+'\n'+strip(l.get('content','')) for l in d.get('lists',[]))+'\n'+d.get('additionalPlain','')
    for l in excerpt(txt): print(' -',l)
