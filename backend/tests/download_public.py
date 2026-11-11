import requests,json,hashlib
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urljoin
root=Path('backend/tests/corpus');pub=root/'public';pub.mkdir(exist_ok=True)
sources=[('irs-w4.pdf','https://www.irs.gov/pub/irs-pdf/fw4.pdf'),('ons-population.xlsx','https://www.ons.gov.uk/file?uri=%2Fpeoplepopulationandcommunity%2Fpopulationandmigration%2Fpopulationestimates%2Fdatasets%2Fpopulationestimatestimeseriesdataset%2Fcurrent%2Fpop.xlsx'),('ons-population.csv','https://www.ons.gov.uk/file?uri=%2Fpeoplepopulationandcommunity%2Fpopulationandmigration%2Fpopulationestimates%2Fdatasets%2Fpopulationestimatestimeseriesdataset%2Fcurrent%2Fpop.csv')]
page='https://www.coventry.gov.uk/downloads/download/7845/two-year-progress-check-template-may-2025'
r=requests.get(page,timeout=30);soup=BeautifulSoup(r.text,'html.parser')
links=[urljoin(page,a['href']) for a in soup.select('a[href]') if '/downloads/file/' in a['href']]
if links:sources.append(('coventry-progress-template.docx',links[0]))
sources.append(('calibre-demo.docx','https://calibre-ebook.com/downloads/demos/demo.docx'))
report=[]
for name,url in sources:
 try:
  r=requests.get(url,timeout=45);r.raise_for_status();p=pub/name
  if name.endswith(('.xlsx','.docx')):assert r.content.startswith(b'PK'),r.headers.get('Content-Type')
  if name.endswith('.pdf'):assert r.content.startswith(b'%PDF')
  p.write_bytes(r.content);report.append({'name':'public/'+name,'path':str(p.resolve()),'source':url,'size':len(r.content),'extension':p.suffix,'sha256':hashlib.sha256(r.content).hexdigest()});print(name,len(r.content),flush=True)
 except Exception as e:print('DOWNLOAD ERROR',name,str(e),flush=True)
(root/'public-manifest.json').write_text(json.dumps(report,indent=2),encoding='utf8')
