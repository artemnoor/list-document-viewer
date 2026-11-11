from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import sys,time,json
sys.path.insert(0,'backend')
from extraction import analyze
p=Path('backend/ocr-check.png')
image=Image.new('RGB',(1200,350),'white')
draw=ImageDraw.Draw(image)
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',48)
draw.text((60,80),'OCR TEST 12345',font=font,fill='black')
image.save(p)
t=time.time()
try:
    result=analyze(p,p.name)
    Path('backend/ocr-check-result.json').write_text(json.dumps({'ocr':result.get('ocr'),'markdown':result['markdown'],'seconds':time.time()-t}),encoding='utf8')
    assert '12345' in result['markdown'], result['markdown']
    print('PASS end-to-end OCR',flush=True)
finally:
    p.unlink(missing_ok=True)
