from pathlib import Path
import json,fitz,cv2,numpy as np
from PIL import Image
items=json.loads(Path('backend/tests/corpus/manifest.json').read_text(encoding='utf8'))
root=Path('backend/tests/corpus/quickviews');root.mkdir(exist_ok=True)
for item in items:
 p=Path(item['path'])
 if not (p.name.startswith('01_') or p.suffix=='.png'):continue
 if p.suffix=='.pdf':
  with fitz.open(p) as d:
   pix=d[0].get_pixmap(matrix=fitz.Matrix(2,2));im=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
 else:im=Image.open(p).convert('RGB')
 im.save(root/(p.stem+'.png'))
 gray=cv2.cvtColor(np.asarray(im),cv2.COLOR_RGB2GRAY);binary=cv2.threshold(gray,0,255,cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)[1]
 h=cv2.morphologyEx(binary,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_RECT,(max(20,im.width//70),1)))
 v=cv2.morphologyEx(binary,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_RECT,(1,max(15,im.height//70))))
 mask=cv2.bitwise_or(h,v);mask=cv2.dilate(mask,np.ones((3,3),np.uint8))
 n,labels,stats,centroids=cv2.connectedComponentsWithStats(mask)
 boxes=[s.tolist() for s in stats[1:] if s[2]>im.width*.2 and s[3]>im.height*.04]
 print(p.suffix,im.size,boxes)
 cv2.imwrite(str(root/(p.stem+'-lines.png')),mask)
