"""Compare saved analysis JSON with manually annotated ground truth, without OCR calls.

Truth format: {"tables":[{"page_no":1,"bbox":[l,t,r,b],"rows":[["value"]],
"cells":[{"row":0,"column":0,"row_span":1,"col_span":1,"bbox":[l,t,r,b]}]}],
"continuations":[{"from_page":1,"to_page":2}]}.
Analysis format: result object or {"result": result, "seconds": ...}.
Tables with annotated bounding boxes are matched by page and overlap; otherwise
the fallback is page/order sequence. Source metric requires annotated boxes.
"""
import argparse, json, re
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path


def norm(value): return ' '.join(str('' if value is None else value).split())
def numeric(value): return bool(re.fullmatch(r'[+−-]?[\d\s]+(?:[.,]\d+)?%?',norm(value)))
def numeric_key(value):
    """Compare numeric meaning across harmless grouping/decimal glyph variants."""
    text=norm(value).replace('\u00a0','').replace(' ','')
    percent=text.endswith('%')
    if percent:text=text[:-1]
    if ',' in text and '.' in text:
        decimal_sep=',' if text.rfind(',')>text.rfind('.') else '.'
        grouping_sep='.' if decimal_sep==',' else ','
        text=text.replace(grouping_sep,'').replace(decimal_sep,'.')
    elif ',' in text:
        text=text.replace(',','.')
    try:
        number=Decimal(text)
        if not number.is_finite():return None
        return (number,percent)
    except InvalidOperation:return None

def value_equal(left,right):
    if numeric(left) and numeric(right):
        a,b=numeric_key(left),numeric_key(right)
        return a is not None and a==b
    return norm(left)==norm(right)
def ratio(n,d): return n/d if d else None


def box(value):
    if isinstance(value, dict) and all(k in value for k in ('l','t','r','b')):
        value=[value[k] for k in ('l','t','r','b')]
    if not isinstance(value, (list, tuple)) or len(value)!=4:
        return None
    if not all(isinstance(v, (int, float)) for v in value): return None
    l,t,r,b=value
    return [min(l,r),min(t,b),max(l,r),max(t,b)]


def iou(a,b):
    a,b=box(a),box(b)
    if not a or not b:return 0
    intersection=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    area=lambda v:(v[2]-v[0])*(v[3]-v[1])
    return intersection/max(1,area(a)+area(b)-intersection)

def evaluate(expected, actual):
    result=actual.get('result',actual)
    layout=result.get('visual_layout') or result.get('ocr_layout') or {}
    tables=[p for p in (layout.get('parts') or result.get('parts',[])) if p.get('kind')=='table' and p.get('rows')]
    remaining=list(tables); truth=expected.get('tables',[]);pairs=[]
    for target in truth:
        page_tables=[t for t in remaining if (t.get('provenance') or [{}])[0].get('page_no')==target.get('page_no')]
        target_box=box(target.get('bbox'))
        if target_box:
            ranked=sorted(((iou(target_box,(t.get('provenance') or [{}])[0].get('bbox')),t) for t in page_tables),key=lambda pair:pair[0],reverse=True)
            found=ranked[0][1] if ranked and ranked[0][0]>=.2 else None
        else:
            found=page_tables[0] if page_tables else None
        if found:remaining.remove(found)
        pairs.append((target,found))
    expected_cells=correct=matched_values=numeric_total=numeric_correct=structure_total=structure_correct=box_total=box_correct=0
    for target,found in pairs:
        actual_rows=(found or {}).get('rows',[])
        cells=Counter(('N',numeric_key(x)) if numeric(x) else ('T',norm(x))
                      for row in actual_rows for x in row if norm(x))
        for i,row in enumerate(target.get('rows',[])):
            for j,value in enumerate(row):
                value=norm(value)
                if not value:continue
                expected_cells+=1
                key=('N',numeric_key(value)) if numeric(value) else ('T',value)
                if cells[key]>0:matched_values+=1;cells[key]-=1
                got=norm(actual_rows[i][j]) if i<len(actual_rows) and j<len(actual_rows[i]) else ''
                equal=value_equal(got,value)
                correct+=equal
                if numeric(value):numeric_total+=1;numeric_correct+=equal
        actual_cells={(c.get('row'),c.get('column')):c for c in (found or {}).get('cells',[])}
        for cell in target.get('cells',[]):
            other=actual_cells.get((cell.get('row'),cell.get('column')), {})
            if 'row_span' in cell or 'col_span' in cell:
                structure_total+=1;structure_correct+=bool(other) and all(cell.get(k,1)==other.get(k,1) for k in ('row_span','col_span'))
            if cell.get('bbox'):
                box_total+=1;a=cell['bbox'];b=other.get('bbox')
                if isinstance(b,dict) and all(k in b for k in ('l','t','r','b')):
                    b=[b[k] for k in ('l','t','r','b')]
                if isinstance(b,(list,tuple)) and len(b)==4:
                    x=max(0,min(a[2],b[2])-max(a[0],b[0]));y=max(0,min(a[3],b[3])-max(a[1],b[1]));inter=x*y
                    area=lambda c:max(0,c[2]-c[0])*max(0,c[3]-c[1])
                    box_correct+=inter/max(1,area(a)+area(b)-inter)>=.5
    links = Counter()
    for group in result.get('logical_tables', []):
        fragments = group.get('fragments', [])
        for previous, current in zip(fragments, fragments[1:]):
            if current.get('continuation'):
                links[(previous.get('page_no'), current.get('page_no'))] += 1
    annotated = Counter((link.get('from_page'), link.get('to_page')) for link in expected.get('continuations', []))
    continuation_matches = sum((annotated & links).values())
    return {'annotation_scope':expected.get('annotation_scope', 'unspecified'),
            'table_recall':ratio(sum(bool(f) for _,f in pairs),len(truth)),
            'cell_recall':ratio(matched_values,expected_cells),'cell_assignment_accuracy':ratio(correct,expected_cells),
            'numeric_exact_match':ratio(numeric_correct,numeric_total),'structure_accuracy':ratio(structure_correct,structure_total),
            'source_accuracy_iou_05':ratio(box_correct,box_total),'processing_seconds':actual.get('seconds'),
            'continuation_recall':ratio(continuation_matches, sum(annotated.values())),
            'continuation_precision':ratio(continuation_matches, sum(links.values())) if annotated else None,
            'counts':{'expected_tables':len(truth),'detected_tables':len(tables),'expected_cells':expected_cells,'numeric_cells':numeric_total,'annotated_spans':structure_total,'annotated_boxes':box_total},
            'note':'Числа сравниваются по значению с учётом пробелов-разделителей тысяч и запятой/точки десятичного разделителя; текст сравнивается после нормализации пробелов. Таблицы сопоставляются по странице и пересечению областей, а без эталонных координат — по порядку. Неаннотированные метрики равны null; связи считаются по номерам страниц и включают предполагаемые.'}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('truth');parser.add_argument('analysis');parser.add_argument('--output');args=parser.parse_args()
    report=evaluate(json.loads(Path(args.truth).read_text(encoding='utf8')),json.loads(Path(args.analysis).read_text(encoding='utf8')))
    text=json.dumps(report,ensure_ascii=False,indent=2)
    if args.output:Path(args.output).write_text(text+'\n',encoding='utf8')
    else:print(text)
