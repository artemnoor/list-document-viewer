from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
from pathlib import Path
import random, math, io, json
import numpy as np
import cv2
import fitz

OUT=Path(__file__).resolve().parent
R=random.Random(73021)
FONT='C:/Windows/Fonts/arial.ttf'; BOLD='C:/Windows/Fonts/arialbd.ttf'
def font(size=28,bold=False): return ImageFont.truetype(BOLD if bold else FONT,size)
def canvas(title,w=1650,h=2250):
 im=Image.new('RGB',(w,h),'white');d=ImageDraw.Draw(im);d.text((100,65),title,font=font(38,True),fill='black');return im

def table(im,x,y,widths,heights,rows,grid=True,fontsize=28, fills=None):
 d=ImageDraw.Draw(im); ys=[y]
 for h in heights: ys.append(ys[-1]+h)
 xs=[x]
 for w in widths:xs.append(xs[-1]+w)
 if fills:
  for r,c,fill in fills:d.rectangle((xs[c],ys[r],xs[c+1],ys[r+1]),fill=fill)
 if grid:
  for xx in xs:d.line((xx,ys[0],xx,ys[-1]),fill=(45,45,45),width=3)
  for yy in ys:d.line((xs[0],yy,xs[-1],yy),fill=(45,45,45),width=3)
 for r,row in enumerate(rows):
  for c,txt in enumerate(row):
   d.multiline_text((xs[c]+12,ys[r]+10),str(txt),font=font(fontsize,r==0),fill=(12,12,12),spacing=7)
 return xs,ys

def save(im,name): im.save(OUT/name,optimize=True)
def page_to_pdf(doc,im):
 page=doc.new_page(width=595,height=842);b=io.BytesIO();im.save(b,format='PNG');page.insert_image(page.rect,stream=b.getvalue());return page

cases=[]
def meta(filename,description,checks):cases.append({'file':filename,'description':description,'checks':checks})

im=canvas('01. Ведомость без границ');rows=[['№','Наименование','Ед.','Количество','Сумма, ₽'],['1','Кабель силовой','м','125,5','35 000,00'],['2','Контроллер связи','шт.','12','85 000,00'],['3','Комплект датчиков','шт.','8','120 400,50'],['4','Плата управления','шт.','16','9 876,54'],['','ИТОГО','','','250 277,04']];table(im,100,210,[100,540,150,260,330],[85]*6,rows,grid=False);save(im,'01_borderless.png');meta('01_borderless.png','Таблица без границ и числовые столбцы',['35 000,00 и 85 000,00 — разные суммы','ИТОГО 250 277,04'])

im=canvas('02. Повернутая таблица');rows=[['Код','Деталь','Материал','Кол-во'],['A-017','Рулевая колонка','Алюминий','18'],['B-204','Кронштейн','Сталь','250'],['C-005','Корпус датчика','Пластик','7']];table(im,120,230,[220,510,450,200],[100]*4,rows);im=im.rotate(4.2,expand=False,fillcolor='white',resample=Image.Resampling.BICUBIC);save(im,'02_rotated_4deg.png');meta('02_rotated_4deg.png','Наклон страницы на 4,2°',['A-017 — 18','B-204 — 250'])

im=canvas('03. Мелкий текст и длинные ячейки');rows=[['№','ФИО','Достижения'],['1','Иванова Мария\nАлексеевна','Роль в команде: руководитель проекта.\nРазработка монолитного рулевого колеса\nиз композиционного материала для болида.\nУчастие в грантовом конкурсе «Первый запуск».'],['2','Сидоров Павел\nИгоревич','Организация тематической площадки\nна выставке ГК «Росатом».\nПроведение расчётов и проверка чертежей.'],['3','Петрова Елена\nСергеевна','Разработка системы автоматизации\nпроектирования технологической оснастки.']];table(im,85,190,[100,390,990],[70,370,300,240],rows,fontsize=24);save(im,'03_long_cells.png');meta('03_long_cells.png','Крупные ячейки с мелким многострочным текстом',['монолитного рулевого колеса из композиционного материала','ФИО и достижения не должны перемешиваться'])

im=canvas('04. Объединённые ячейки');d=ImageDraw.Draw(im);x=[100,380,700,1030,1470];y=[210,310,410,510,610,710];
for xx in [x[0],x[1],x[4]]:d.line((xx,y[0],xx,y[-1]),fill='black',width=3)
for xx in [x[2],x[3]]:d.line((xx,y[1],xx,y[-1]),fill='black',width=3)
for yy in y:d.line((x[0],yy,x[4],yy),fill='black',width=3)
d.text((120,230),'Период',font=font(30,True),fill='black');d.text((620,230),'Показатели проекта',font=font(30,True),fill='black')
for r,row in enumerate([['Год','План','Факт','Отклонение'],['2023','100','95','−5'],['2024','120','123','+3'],['2025','140','141','+1']]):
 for c,v in enumerate(row):d.text((x[c]+15,y[r+1]+25),v,font=font(29,r==0),fill='black')
save(im,'04_merged_headers.png');meta('04_merged_headers.png','Общий заголовок на три столбца',['Показатели проекта объединяет три колонки','2024: план 120, факт 123, отклонение +3'])

im=canvas('05. Бледная копия');rows=[['Документ','Дата','Номер','Значение'],['Акт приёмки','12.02.2025','А-035','35 000'],['Счёт','08.03.2025','С-085','85 000'],['Накладная','19.04.2025','Н-118','118 500']];table(im,100,240,[430,300,300,350],[110]*4,rows,fontsize=29);im=ImageEnhance.Contrast(im).enhance(.37).filter(ImageFilter.GaussianBlur(.75));save(im,'05_faded_blurred.png');meta('05_faded_blurred.png','Низкий контраст и размытие',['А-035: 35 000','С-085: 85 000'])

im=canvas('06. Фото таблицы',1400,1150);rows=[['Код','Описание','Цена'],['01','Набор инструмента','3 500'],['02','Датчик давления','8 500'],['03','Узел крепления','1 200']];table(im,80,170,[200,690,330],[120]*4,rows,fontsize=31);arr=np.array(im);src=np.float32([[0,0],[1399,0],[1399,1149],[0,1149]]);dst=np.float32([[100,70],[1320,0],[1399,1080],[0,1149]]);warped=cv2.warpPerspective(arr,cv2.getPerspectiveTransform(src,dst),(1400,1150),borderValue=(190,190,190));save(Image.fromarray(warped),'06_perspective.png');meta('06_perspective.png','Перспектива и наклон, как на фотографии',['Датчик давления — 8 500','Набор инструмента — 3 500'])

im=canvas('07. Числа, похожие друг на друга');rows=[['Строка','Исходное','Проверка','Примечание'],['1','35000','85000','разные'],['2','0','8','разные'],['3','1 005,80','1 005,08','разные'],['4','−12,50','12,50','знак'],['5','2025-01-09','2025-09-01','даты']];table(im,100,220,[200,350,350,480],[100]*6,rows);save(im,'07_ambiguous_numbers.png');meta('07_ambiguous_numbers.png','Похожие цифры, десятичные дроби, отрицательное число и даты',['35000 ≠ 85000','1 005,80 ≠ 1 005,08','−12,50 ≠ 12,50'])

# Native PDF text, including a full-page background image; no OCR is necessary.
doc=fitz.open();page=doc.new_page(width=595,height=842);pix=Image.new('RGB',(1190,1684),(250,250,247));buf=io.BytesIO();pix.save(buf,format='PNG');page.insert_image(page.rect,stream=buf.getvalue());page.insert_font(fontname='cyr',fontfile=FONT)
for y,line in [(75,'08. Цифровой PDF: текстовый слой'),(130,'Номер   Наименование                  Сумма'),(170,'1           Испытательный стенд             35000'),(210,'2           Привод управления                 85000'),(250,'3           Комплект датчиков                  120400'),(350,'Текст и цифры доступны для выделения.')]:page.insert_text((45,y),line,fontname='cyr',fontsize=13)
doc.save(OUT/'08_digital_text_over_background.pdf');doc.close();meta('08_digital_text_over_background.pdf','Цифровой PDF с текстовым слоем над фоновым изображением',['Текст должен извлекаться без OCR','35000 и 85000'])

# Multipage continuation with a row cut across pages.
doc=fitz.open()
for idx in (1,2):
 im=canvas(f'09. Продолжение таблицы — страница {idx}');
 if idx==1: rows=[['№','Участник','Описание'],['1','Иванова М. А.','Руководитель команды.'],['2','Петров И. С.','Разработка системы автоматизации\nпроектирования технологической']];heights=[100,230,380]
 else: rows=[['','','оснастки для гоночного болида.'],['3','Сидорова Е. П.','Организация выставки.']];heights=[250,250]
 table(im,100,1250 if idx == 1 else 170,[150,430,850],heights,rows,fontsize=30);page_to_pdf(doc,im)
doc.save(OUT/'09_multipage_split_row.pdf');doc.close();meta('09_multipage_split_row.pdf','Две страницы, одна строка разделена между страницами',['Строка 2: Разработка системы автоматизации проектирования технологической оснастки для гоночного болида','Сохранить привязку к обеим страницам'])

# Mixed PDF: native text page and scanned image page.
doc=fitz.open();page=doc.new_page(width=595,height=842);page.insert_font(fontname='cyr',fontfile=FONT);page.insert_text((50,70),'10. Цифровая страница: договор № 731 от 11.11.2026',fontname='cyr',fontsize=15);page.insert_text((50,110),'Контрагент: ООО «Пример». Сумма: 35 000 рублей.',fontname='cyr',fontsize=14)
im=canvas('10. Скан приложения');table(im,120,220,[240,700,380],[110,130,130],[['№','Позиция','Стоимость'],['1','Испытание прибора','35 000'],['2','Калибровка','85 000']],fontsize=32);page_to_pdf(doc,im);doc.save(OUT/'10_mixed_native_and_scan.pdf');doc.close();meta('10_mixed_native_and_scan.pdf','Первая страница цифровая, вторая — скан таблицы',['Страница 1: извлечь текст из PDF','Страница 2: OCR для изображения','35 000 и 85 000'])

(OUT/'manifest.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf8')
lines=['# Набор сложных примеров','', 'Все сведения вымышлены. Изображения синтетические. Распознавание не запускалось.','']
for c in cases:lines+=['## '+c['file'],c['description'],'']+['- '+x for x in c['checks']]+['']
(OUT/'README.md').write_text('\n'.join(lines),encoding='utf8')
print('Created',len(cases),'fixtures in',OUT)
