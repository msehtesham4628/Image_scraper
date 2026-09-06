import json, re
from pathlib import Path
from urllib.parse import urlparse

SRC=Path(__file__).resolve().parent.parent/'fresh_scrape'
OUT=Path(__file__).resolve().parent
LIMIT=1000
PLACEHOLDER=('woocommerce-placeholder','placeholder','loading','spinner','default-image')

def clean_text(v):
    if v is None:return ''
    s=str(v).replace('\ufffd','').strip()
    return re.sub(r'\s+',' ',s)

def image_ok(u):
    if not isinstance(u,str) or not u.startswith('http'): return False
    x=u.lower()
    return 'worldhookahmarket.com' in (urlparse(u).netloc or '').lower() and not any(p in x for p in PLACEHOLDER)

def normalize(p):
    name=clean_text(p.get('product_name'))
    desc=clean_text(p.get('description'))
    price=clean_text(p.get('price'))
    sku=''
    imgs=[];seen=set()
    for u in p.get('image_urls',[]) if isinstance(p.get('image_urls',[]),list) else []:
        if image_ok(u) and u not in seen:seen.add(u);imgs.append(u)
    url=clean_text(p.get('product_url'))
    if not name or not url:return None
    # Brand/category were not present in the current exported records. Preserve them when available.
    brand=clean_text(p.get('brand'))
    category=clean_text(p.get('category'))
    return {'product_name':name,'description':desc,'price':price,'sku':sku,'brand':brand,'category':category,'image_urls':imgs,'product_url':url}

def main():
    records=[];stats={'files':0,'read':0,'duplicates':0,'invalid':0,'placeholder_images_removed':0}
    seen_urls=set()
    for f in sorted(SRC.glob('products-*.json'), key=lambda x:int(re.search(r'(\d+)',x.name).group(1))):
        stats['files']+=1
        try:data=json.loads(f.read_text(encoding='utf-8'))
        except Exception as e: print('BAD JSON',f,e);continue
        if not isinstance(data,list):continue
        for raw in data:
            stats['read']+=1
            before=len(raw.get('image_urls',[])) if isinstance(raw,dict) and isinstance(raw.get('image_urls',[]),list) else 0
            p=normalize(raw if isinstance(raw,dict) else {})
            if not p:stats['invalid']+=1;continue
            stats['placeholder_images_removed'] += before-len(p['image_urls'])
            key=p['product_url'].lower().rstrip('/')
            if key in seen_urls:stats['duplicates']+=1;continue
            seen_urls.add(key);records.append(p)
    for old in OUT.glob('products-*.json'): old.unlink()
    for i in range(0,len(records),LIMIT):
        n=i//LIMIT+1
        (OUT/f'products-{n}.json').write_text(json.dumps(records[i:i+LIMIT],ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'validation.json').write_text(json.dumps({**stats,'output_products':len(records),'output_files':(len(records)+LIMIT-1)//LIMIT},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({**stats,'output_products':len(records),'output_files':(len(records)+LIMIT-1)//LIMIT},indent=2))

if __name__=='__main__':main()
