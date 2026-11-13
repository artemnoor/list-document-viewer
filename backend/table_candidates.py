"""Register table candidates for the same physical page region."""
from copy import deepcopy
import re


def same_region(left, right):
    left_provenance = left.get('provenance') or []
    right_provenance = right.get('provenance') or []
    if not left_provenance or not right_provenance:
        return False
    a, b = left_provenance[0], right_provenance[0]
    if a.get('page_no') is None or a.get('page_no') != b.get('page_no'): return False
    a, b = a.get('bbox', {}), b.get('bbox', {})
    if not all(k in a and k in b for k in ('l','t','r','b')): return False
    intersection = max(0, min(a['r'],b['r'])-max(a['l'],b['l'])) * max(0,min(a['b'],b['b'])-max(a['t'],b['t']))
    area_a = max(0,a['r']-a['l'])*max(0,a['b']-a['t'])
    area_b = max(0,b['r']-b['l'])*max(0,b['b']-b['t'])
    if not area_a or not area_b:
        return False
    if intersection/area_a >= .6 and intersection/area_b >= .6:
        return True
    # Raster orientation can produce one page-sized region and one tighter grid.
    # Containment alone is not identity: require strong independent value evidence.
    if intersection/min(area_a,area_b) < .9 or left.get('source') != 'ocr_raster_grid' or right.get('source') != 'ocr_raster_grid':
        return False
    def numbers(table):
        values=set()
        for row in table.get('rows', []):
            for value in row:
                value=re.sub(r'\s+', '', str('' if value is None else value))
                if re.fullmatch(r'[+−\-]?\d[\d.,%]*', value):
                    values.add(value)
        return values
    left_values,right_values=numbers(left),numbers(right)
    overlap=len(left_values & right_values)
    return bool(overlap >= 4 and overlap >= .8*len(left_values) and overlap >= .8*len(right_values))


def snapshot(table):
    return deepcopy({k:v for k,v in table.items() if k not in ('table_candidates','arbitration')})
