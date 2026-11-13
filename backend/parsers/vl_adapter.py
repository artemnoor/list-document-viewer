"""Convert saved PaddleOCR-VL outputs for offline, experimental comparison.

This module does not call a service or select a model for document processing.
"""
if __package__ in (None, ''):
    from pathlib import Path
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from parsers.mineru_adapter import _grid
from parsers.ppstructure_adapter import _box


def page_layout(path):
    from pathlib import Path
    path=Path(path)
    if path.suffix.lower()=='.pdf':
        import fitz
        with fitz.open(stream=path.read_bytes(),filetype='pdf') as document:
            return {'pages':{str(i+1):{'size':{'width':page.rect.width,'height':page.rect.height}}
                             for i,page in enumerate(document)}}
    from PIL import Image
    with Image.open(path) as image:
        return {'pages':{'1':{'size':{'width':image.width,'height':image.height}}}}


def enable_bfloat16_numpy_compat(paddle):
    """Work around Paddle builds that cannot ingest NumPy bfloat16 arrays."""
    if getattr(paddle, '_vl_bfloat16_numpy_compat', False):
        return
    original = paddle.to_tensor

    def to_tensor(data, *args, **kwargs):
        if getattr(getattr(data, 'dtype', None), 'name', None) == 'bfloat16':
            data = data.astype('float32')
            kwargs.setdefault('dtype', paddle.bfloat16)
        return original(data, *args, **kwargs)

    paddle.to_tensor = to_tensor
    paddle._vl_bfloat16_numpy_compat = True


def candidates_from_result(result, page_no, scale_x=1, scale_y=1, version='v1.5'):
    if version not in {'v1.5', 'v1.6'}:
        raise ValueError('Only explicitly selected PaddleOCR-VL v1.5 or v1.6 are supported')
    result = result.get('res', result)
    candidates=[]
    for block in result.get('parsing_res_list', []):
        if block.get('block_label') != 'table':
            continue
        text=block.get('block_content') or ''
        if not isinstance(text,str) or '<table' not in text.lower():
            continue
        raw_box=block.get('block_bbox')
        if raw_box is None:
            continue
        bbox=_box(raw_box,scale_x,scale_y)
        if not bbox or bbox[0]>=bbox[2] or bbox[1]>=bbox[3]:
            continue
        rows,cells=_grid(text)
        if not rows:
            continue
        rect=dict(zip(('l','t','r','b'),bbox),coord_origin='TOPLEFT')
        candidates.append({'kind':'table','source':'paddleocr_vl_'+version,'rows':rows,'cells':cells,
                           'provenance':[{'page_no':page_no,'bbox':rect}],
                           'table_warning':'Экспериментальный PaddleOCR-VL не предоставил координаты ячеек; проверьте таблицу.'})
    return candidates


def parse_pages(path, extension, layout, pages, version, max_new_tokens=None):
    """Run a selected local model; never use a remote inference endpoint."""
    if version not in {'v1.5','v1.6'}:
        raise ValueError('Select v1.5 or v1.6 explicitly')
    if max_new_tokens is not None and max_new_tokens < 1:
        raise ValueError('max_new_tokens must be a positive integer')
    import os
    import numpy as np
    if os.environ.get('PADDLE_VL_BFLOAT16_COMPAT') == '1':
        import paddle
        enable_bfloat16_numpy_compat(paddle)
    from paddleocr import PaddleOCRVL
    from ocr_layout import _page_image
    pipeline=PaddleOCRVL(pipeline_version=version,vl_rec_backend='native',
                         use_doc_orientation_classify=False,use_doc_unwarping=False,
                         use_chart_recognition=False,format_block_content=False,
                         enable_mkldnn=False,device=os.environ.get('PADDLE_VL_DEVICE','cpu'))
    candidates=[]
    for page in sorted(pages):
        size=layout['pages'][str(page)]['size']
        with _page_image(path,extension,page) as image:
            image=image.convert('RGB')
            predict_kwargs={}
            if max_new_tokens is not None:
                predict_kwargs['max_new_tokens']=max_new_tokens
            for output in pipeline.predict(np.asarray(image)[:,:,::-1].copy(),**predict_kwargs):
                candidates.extend(candidates_from_result(output.json,page,
                                  size['width']/image.width,size['height']/image.height,version))
    return candidates


def main():
    import argparse
    import json
    from pathlib import Path
    import time
    parser=argparse.ArgumentParser(description='Experimental local PaddleOCR-VL benchmark output')
    parser.add_argument('input',type=Path)
    parser.add_argument('--version',required=True,choices=('v1.5','v1.6'))
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--max-new-tokens',type=int,default=None)
    args=parser.parse_args()
    layout=page_layout(args.input)
    start=time.monotonic()
    tables=parse_pages(args.input,args.input.suffix.lower(),layout,[int(p) for p in layout['pages']],
                       args.version,args.max_new_tokens)
    result={'result':{'parts':tables,'visual_layout':{'pages':layout['pages'],'parts':tables},
                      'experimental_model':'PaddleOCR-VL-'+args.version},'seconds':round(time.monotonic()-start,3)}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')


if __name__=='__main__':
    main()
