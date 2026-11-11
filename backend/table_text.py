"""Conservative table-only OCR normalization; retain unmodified recognition."""
from copy import deepcopy
import re

LOOKALIKE=str.maketrans('ABCEHKMOPTXYabceopxy','АВСЕНКМОРТХУавсеорху')
HEADERS={'СУММА','МАРТ','ИТОГО','КОД','СТАТЬЯ','КОЛИЧЕСТВО','ЯНВАРЬ','ФЕВРАЛЬ'}

def normalize_table_text(table):
    result=deepcopy(table);rows=result.get('rows',[]);cells=result.get('cells',[])
    if not rows:return result
    cyrillic=sum(bool(re.search('[А-Яа-яЁё]',str(value or ''))) for row in rows[:2] for value in row)
    columns=max(map(len,rows),default=0);numeric=set()
    for column in range(columns):
        values=[str(row[column]).strip() for row in rows[1:] if column<len(row) and str(row[column] or '').strip()]
        numeric_values=sum(bool(re.fullmatch(r'[+\-]?\d[\d\s.,%]*',value)) for value in values)
        ambiguous=sum(value in {'O','o','О','о'} for value in values)
        if numeric_values>=2 and numeric_values>=max(1,numeric_values+ambiguous)*.66:numeric.add(column)
    for item in cells:
        row,col=item.get('row',-1),item.get('column',-1)
        if not (0<=row<len(rows) and 0<=col<len(rows[row])):continue
        raw=str(item.get('text',''));new=raw
        if row<2 and cyrillic>=1:
            translated=raw.translate(LOOKALIKE)
            if translated.upper() in HEADERS:new=translated
        if row>=1 and col in numeric and raw.strip() in {'O','o','О','о'}:new='0'
        if new!=raw:
            item['raw_text']=raw;item['text']=new;item['correction']='context_heuristic';rows[row][col]=new
    return result
