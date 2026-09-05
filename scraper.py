import json, os, re, time
from urllib.parse import urljoin, urlparse, urlunparse
import requests
from bs4 import BeautifulSoup

BASE_URL="https://worldhookahmarket.com"
PROGRESS_FILE="products_progress.json"
PART_SIZE=1000
FRESH_SCRAPE=os.getenv("FRESH_SCRAPE","0")=="1"

session=requests.Session(); session.headers.update({"User-Agent":"Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/140.0 Mobile Safari/537.36"})

def clean_url(url):
 p=urlparse(url); return urlunparse((p.scheme,p.netloc,p.path.rstrip("/"),"","",""))
def is_product_url(url):
 u=clean_url(url).lower(); return "/product/" in u or "/products/" in u or "/p/" in u
def same_domain(url): return urlparse(url).netloc.lower() in {"worldhookahmarket.com","www.worldhookahmarket.com"}
def get_page(url):
 try:
  r=session.get(url,timeout=60)
  return r.text if r.status_code==200 else None
 except Exception as e: print(f"REQUEST ERROR: {e}"); return None

def text_one(soup,selectors):
 for s in selectors:
  e=soup.select_one(s)
  if e:
   t=e.get_text(" ",strip=True)
   if t:return t
 return ""

def jsonld_objects(soup):
 out=[]
 for n in soup.select("script[type='application/ld+json']"):
  try:
   d=json.loads(n.string or n.get_text())
   if isinstance(d,list):out+=d
   elif isinstance(d,dict) and isinstance(d.get("@graph"),list):out+=d["@graph"]
   elif isinstance(d,dict):out.append(d)
  except:pass
 return out

def product_jsonld(soup):
 for o in jsonld_objects(soup):
  if isinstance(o,dict) and str(o.get("@type","")).lower()=="product":return o
 return {}

def bad_image(u):
 return any(x in u.lower() for x in ("logo","cart-svgrepo","subscribe","wait-time","spinner","loading","placeholder","avatar","gravatar","favicon","payment","facebook","instagram","youtube","twitter","whatsapp"))

def images(soup,page):
 selectors=[".woocommerce-product-gallery__wrapper img",".woocommerce-product-gallery img",".product-gallery img",".product-images img",".product__images img",".single-product img.wp-post-image"]
 out=[]; seen=set()
 for s in selectors:
  for img in soup.select(s):
   vals=[img.get(a) for a in ("data-large_image","data-src","data-lazy-src","data-original","src")]
   ss=img.get("data-srcset") or img.get("srcset")
   if ss: vals += [x.strip().split()[0] for x in ss.split(",") if x.strip()]
   for v in vals:
    if not v:continue
    u=urljoin(page,str(v).strip())
    if u.startswith("http") and u not in seen and not bad_image(u):seen.add(u);out.append(u)
  if out:break
 if not out:
  o=product_jsonld(soup); vals=o.get("image",[]) if isinstance(o,dict) else []
  if isinstance(vals,str):vals=[vals]
  for v in vals if isinstance(vals,list) else []:
   u=urljoin(page,str(v).strip())
   if u.startswith("http") and u not in seen and not bad_image(u):seen.add(u);out.append(u)
 return out[:20]

def price(v):
 m=re.search(r"(\d+(?:\.\d{1,2})?)",str(v or "").replace(",","")); return f"{float(m.group(1)):.2f}" if m else "0.00"

def brand_category(soup,o):
 b=c=""
 if isinstance(o,dict):
  x=o.get("brand"); b=str(x.get("name") or "").strip() if isinstance(x,dict) else str(x or "").strip()
  x=o.get("category"); c=str(x[0]).strip() if isinstance(x,list) and x else str(x or "").strip()
 b=b or text_one(soup,[".product_meta .brand",".product-brand",".brand-name","[itemprop='brand']"])
 c=c or text_one(soup,[".product_meta .posted_in",".product-category",".product-categories","[itemprop='category']"])
 return b,c

def extract(url):
 html=get_page(url)
 if not html:return None
 soup=BeautifulSoup(html,"html.parser"); o=product_jsonld(soup)
 name=str(o.get("name") or "").strip() if o else ""; name=name or text_one(soup,["h1.product_title","h1.product-title","h1","[itemprop='name']"])
 desc=str(o.get("description") or "").strip() if o else ""; desc=desc or text_one(soup,[".woocommerce-product-details__short-description",".product-description",".product__description","[itemprop='description']",".description"])
 p="0.00"
 if o:
  off=o.get("offers"); off=off[0] if isinstance(off,list) and off else off
  if isinstance(off,dict):p=price(off.get("price"))
 if p=="0.00":
  e=soup.select_one("[itemprop='price']");p=price(e.get("content") if e else "")
 if p=="0.00":p=price(text_one(soup,[".price",".product-price",".product__price"]))
 sku=str(o.get("sku") or "").strip() if o else ""; sku=sku or text_one(soup,[".sku","[itemprop='sku']"])
 b,c=brand_category(soup,o); imgs=images(soup,url)
 if not name and p=="0.00" and not imgs:return None
 return {"product_name":name,"description":desc,"price":p,"sku":sku,"brand":b,"category":c,"image_urls":imgs,"product_url":clean_url(url)}

def save_parts(products):
 for fn in [x for x in os.listdir(".") if re.fullmatch(r"products-\d+\.json",x)]:
  try:os.remove(fn)
  except:pass
 for i in range(0,len(products),PART_SIZE):
  n=i//PART_SIZE+1
  with open(f"products-{n}.json","w",encoding="utf-8") as f:json.dump(products[i:i+PART_SIZE],f,ensure_ascii=False,indent=2)

def links():
 q=[BASE_URL];seen=set();prods=set()
 while q:
  u=clean_url(q.pop(0))
  if u in seen or not same_domain(u):continue
  seen.add(u);print(f"[PAGE {len(seen)}] {u}")
  h=get_page(u)
  if not h:continue
  s=BeautifulSoup(h,"html.parser")
  for a in s.find_all("a",href=True):
   x=clean_url(urljoin(u,a["href"]))
   if not same_domain(x):continue
   if is_product_url(x):prods.add(x)
   elif x not in seen:q.append(x)
  time.sleep(.1)
 print(f"CRAWL COMPLETE — Pages: {len(seen)} — Products: {len(prods)}")
 return sorted(prods)

def main():
 print(f"Fresh scrape: {'YES' if FRESH_SCRAPE else 'NO'} | Part size: {PART_SIZE}")
 urls=links()
 if not urls:return
 products=[]
 for i,u in enumerate(urls,1):
  print(f"[{i}/{len(urls)}] {u}")
  try:
   p=extract(u)
   if p:products.append(p); print(f" ✓ {p['product_name']} | {p['brand']} | {p['category']} | Images: {len(p['image_urls'])}")
  except Exception as e:print(f" ERROR: {e}")
  if i%50==0:save_parts(products); print(f"  Saved {len(products)} products across {((len(products)-1)//PART_SIZE)+1 if products else 0} files")
  time.sleep(.3)
 save_parts(products)
 with open(PROGRESS_FILE,"w",encoding="utf-8") as f:json.dump(products,f,ensure_ascii=False,indent=2)
 print(f"FINISHED — Products: {len(products)} — Files: {(len(products)+PART_SIZE-1)//PART_SIZE} — Image URLs: {sum(len(p.get('image_urls',[])) for p in products)}")

if __name__=="__main__":main()
