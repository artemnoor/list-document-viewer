import io
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import polza_document_review as review


class DocumentReviewCacheTests(unittest.TestCase):
    def setUp(self):
        with review._PAGE_RESPONSE_CACHE_LOCK:
            review._PAGE_RESPONSE_CACHE.clear()
        with review._PAGE_RESPONSE_CACHE_LOCK:
            review._STRUCTURE_RESPONSE_CACHE.clear()
        self.part = {'kind': 'text', 'text': 'Исходный текст', 'provenance': [
            {'page_no': 1, 'bbox': {'l': 10, 't': 20, 'r': 100, 'b': 40}}]}
        self.result = {'parts': [self.part], 'visual_layout': {'pages': {'1': {'size': {'width': 200, 'height': 100}}}}}

    @staticmethod
    def response():
        content = {'suggestions': [{
            'action': 'replace_text', 'target_index': 0, 'row': None, 'column': None,
            'target_cell_id': None,
            'after_row': None, 'bbox': [50, 200, 500, 400], 'proposed': 'Исправленный текст',
            'reason': 'OCR', 'evidence': 'На изображении'}]}
        return io.BytesIO(json.dumps({'choices': [{'message': {'content': json.dumps(content, ensure_ascii=False)}}],
                                     'usage': {'cost_rub': 0.01}}).encode())

    @staticmethod
    def structure_response(tables=None):
        content = {'tables': tables or []}
        return io.BytesIO(json.dumps({'choices': [{'message': {'content': json.dumps(content, ensure_ascii=False)}}],
                                     'usage': {'cost_rub': 0}}).encode())

    def call_review_page(self):
        def respond(request, **kwargs):
            payload = json.loads(request.data)
            name = payload.get('response_format', {}).get('json_schema', {}).get('name')
            if name == 'document_table_structure':
                return self.structure_response()
            if name == 'document_review':
                return self.response()
            if name == 'independent_page_lines':
                return io.BytesIO(json.dumps({'choices':[{'message':{'content':'{"lines":[]}'}}]}).encode())
            return io.BytesIO(json.dumps({'choices': [{'message': {'content': json.dumps(
                {'observed': 'Исправленный текст'}, ensure_ascii=False)}}], 'usage': {'cost_rub': 0.01}}).encode())
        with patch.dict('os.environ', {'POLZA_AI_API_KEY': 'test-key',
                                       'POLZA_DOCUMENT_REVIEW_CACHE_ENABLED': '1'}), \
             patch('ocr_layout._page_image', return_value=Image.new('RGB', (200, 100), 'white')), \
             patch('urllib.request.urlopen', side_effect=respond) as request:
            result = review._review_page(Path('unused.png'), '.png', self.result, 1, 'parts', self.result['parts'],
                                         source_bytes=b'source-image')
        return result, request

    def test_exact_request_reuses_result_without_reusing_suggestion_id(self):
        first, first_request = self.call_review_page()
        second, second_request = self.call_review_page()

        self.assertEqual(first_request.call_count, 3)  # blank source skips independent lines
        second_request.assert_not_called()
        self.assertEqual(first['suggestions'][0]['proposed'], second['suggestions'][0]['proposed'])
        self.assertEqual(first['suggestions'][0]['target_signature'], second['suggestions'][0]['target_signature'])
        self.assertNotEqual(first['suggestions'][0]['id'], second['suggestions'][0]['id'])
        self.assertEqual(first['cost_rub'], 0.02)
        self.assertEqual(second['cost_rub'], 0)
        self.assertFalse(first['cache_hit'])
        self.assertTrue(second['cache_hit'])

    def test_independent_read_detects_a_missing_line_without_seeing_ocr(self):
        answer={'choices':[{'message':{'content':json.dumps({'lines':[
            {'text':'Correct text','bbox':[50,200,500,400]},
            {'text':'Missing line','bbox':[50,600,900,800]}]})}}]}
        parts, _, source, _ = review._text_parts(self.result['parts'],1,{'width':200,'height':100})
        with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(answer).encode())) as call:
            proposals,_=review._independent_text_proposals(Image.new('RGB',(200,100)),parts,source,
                {'width':200,'height':100},'model','key')
        self.assertEqual([s['action'] for s in proposals],['replace_text','add_text'])
        self.assertNotIn(self.part['text'],json.loads(call.call_args.args[0].data)['messages'][0]['content'][0]['text'])

    def test_header_homoglyphs_do_not_change_identifier_alphabet(self):
        self.assertEqual(review._literal_read_key('AKT № 118 OT 2026'), 'АКТ № 118 ОТ 2026')
        self.assertNotEqual(review._literal_read_key('CB-0426'), review._literal_read_key('СВ-0426'))
        self.assertEqual(review._preserve_identifier_script('СВ-О426','CB-0426'),'СВ-0426')
        self.assertEqual(review._preserve_identifier_script('ADM-75','АДМ-75'),'АДМ-75')

    def test_model_box_is_snapped_to_visible_line(self):
        from PIL import ImageDraw
        image=Image.new('RGB',(500,500),'white');draw=ImageDraw.Draw(image)
        draw.rectangle((100,200,300,215),fill='black')
        box=review._snap_text_bbox(image,[190,390,620,430])
        self.assertLessEqual(box[1],400)
        self.assertGreaterEqual(box[3],430)

    def test_new_text_is_inserted_at_source_position(self):
        later={'kind':'text','text':'later','provenance':[{'page_no':1,'bbox':{'l':0,'t':60,'r':80,'b':70}}]}
        new={'kind':'text','text':'missing','review_suggestion_id':'new','provenance':[{'page_no':1,'bbox':{'l':0,'t':45,'r':80,'b':55}}]}
        result={'parts':[self.part,later],'visual_layout':{'parts':[self.part,later]}}
        review._append_review_part(result,new)
        self.assertEqual([p['text'] for p in result['parts']],[self.part['text'],'missing','later'])
        self.assertEqual([p['text'] for p in result['visual_layout']['parts']],[self.part['text'],'missing','later'])

    def test_observed_alternative_requires_another_source_confirmation(self):
        size={'width':200,'height':100}
        parts,_,source,_=review._text_parts(self.result['parts'],1,size)
        raw={'action':'replace_text','target_index':0,'bbox':[50,200,500,400],'proposed':'Wrong proposal'}
        seed=review._normalise_suggestions([raw],1,parts,source,'parts',size)[0]
        seed.update(status='verification_failed',source_observed='Correct source')
        for observed, should_recover in [('Correct source',True),('Another reading',False)]:
            answer={'choices':[{'message':{'content':json.dumps({'observed':observed})}}]}
            with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(answer).encode())) as call:
                values,_,_=review._recover_literal_edits([dict(seed)],[],Image.new('RGB',(200,100)),
                    size,'model','key',1,parts,source,'parts')
            self.assertEqual(call.call_count,1)
            self.assertEqual(bool(values[0].get('source_verified')),should_recover)
            if should_recover:
                self.assertEqual(values[0]['proposed'],'Correct source')
                self.assertEqual(len(values[0]['verification_attempts']),1)

    def test_wrong_proposal_is_rejected_when_two_reads_confirm_original(self):
        size={'width':200,'height':100}
        parts,_,source,_=review._text_parts(self.result['parts'],1,size)
        raw={'action':'replace_text','target_index':0,'bbox':[50,200,500,400],'proposed':'Wrong proposal'}
        seed=review._normalise_suggestions([raw],1,parts,source,'parts',size)[0]
        seed.update(status='verification_failed',source_observed=seed['original'])
        probe=dict(seed,proposed=seed['original'],status='pending')
        answer={'choices':[{'message':{'content':json.dumps({'observed':seed['original']})}}]}
        with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(answer).encode())):
            values,_,_=review._recover_literal_edits([seed],[probe],Image.new('RGB',(200,100)),
                size,'model','key',1,parts,source,'parts')
        self.assertEqual(values[0]['status'],'rejected')
        self.assertFalse(values[0].get('source_verified'))

    def test_identical_model_proposals_are_deduplicated(self):
        raw = json.loads(json.loads(self.response().read())['choices'][0]['message']['content'])['suggestions'][0]
        parts, _, source, _ = review._text_parts(self.result['parts'], 1, {'width':200,'height':100})
        proposals = review._normalise_suggestions([raw, dict(raw)], 1, parts, source, 'parts', {'width':200,'height':100})
        self.assertEqual(len(proposals), 1)

    def test_confirmed_existing_grid_does_not_authorize_an_extra_row(self):
        proposal = {'action':'add_table_row','target_index':0,'status':'pending'}
        review._gate_structural_suggestions([proposal], {'matched_tables':{0:'confirmed'}, 'tables':[]},
            [{'rows':[['a','b']]}], {'width':200,'height':100})
        self.assertEqual(proposal['status'], 'verification_failed')

    def test_changed_recognized_text_invalidates_cached_result(self):
        first, _ = self.call_review_page()
        self.part['text'] = 'Изменённый распознанный текст'
        second, request = self.call_review_page()

        self.assertEqual(request.call_count, 2)
        self.assertEqual(first['suggestions'][0]['proposed'], second['suggestions'][0]['proposed'])
        self.assertFalse(second['cache_hit'])

    def test_changed_target_geometry_invalidates_cached_result(self):
        self.call_review_page()
        self.part['provenance'][0]['bbox']['l'] = 11
        second, request = self.call_review_page()

        self.assertEqual(request.call_count, 2)
        self.assertFalse(second['cache_hit'])

    def test_review_reads_document_once_and_shares_source_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'two-pages.pdf'
            document = fitz.open()
            document.new_page()
            document.new_page()
            document.save(path)
            document.close()

            original_read_bytes = Path.read_bytes
            read_count = 0
            captured_bytes = []
            capture_lock = threading.Lock()

            def counted_read_bytes(target):
                nonlocal read_count
                if target == path:
                    read_count += 1
                return original_read_bytes(target)

            def fake_review_page(*args, source_bytes=None, **kwargs):
                with capture_lock:
                    captured_bytes.append(source_bytes)
                return {'status': 'complete', 'model': review.MODEL, 'suggestions': [], 'cost_rub': 0}

            with patch.dict(os.environ, {'POLZA_AI_API_KEY': 'test-key', 'POLZA_DOCUMENT_REVIEW_WORKERS': '2'}), \
                 patch.object(Path, 'read_bytes', counted_read_bytes), \
                 patch.object(review, '_review_page', side_effect=fake_review_page):
                result = review.review_document(path, '.pdf', {'parts': []})

        self.assertEqual(result['status'], 'complete')
        self.assertEqual(read_count, 1)
        self.assertEqual(len(captured_bytes), 2)
        self.assertIs(captured_bytes[0], captured_bytes[1])

    def test_document_review_remains_enabled_when_local_ocr_is_disabled(self):
        page = {'status': 'complete', 'model': review.MODEL, 'suggestions': [], 'cost_rub': 0.01}
        with patch.dict(os.environ, {'POLZA_AI_API_KEY': 'test-key', 'POLZA_OCR_ENABLED': '0',
                                    'POLZA_DOCUMENT_REVIEW_ENABLED': '1'}), \
             patch.object(review, '_review_page', return_value=page) as call:
            result = review.review_document(Path('source.txt'), '.txt', {'parts': []})
        self.assertEqual(result['status'], 'complete')
        call.assert_called_once()

    def test_native_replacement_must_match_original_source_address(self):
        current = {'kind': 'cell', 'sheet': 'Data', 'coordinate': 'A1',
                   'value': 'misread', 'display_value': 'misread'}
        original = {'kind': 'cell', 'sheet': 'Data', 'coordinate': 'A1',
                    'value': 'correct', 'display_value': 'correct'}
        raw = {'action': 'replace_text', 'target_index': 0, 'proposed': 'correct'}
        page_parts, _, result_parts, _ = review._text_parts([current], None)
        suggestion = review._normalise_suggestions([raw], 1, page_parts, result_parts,
                                                   'source_text')[0]
        suggestion = review._verify_native_suggestions([suggestion], result_parts, [original])[0]
        self.assertTrue(suggestion['source_verified'])
        result = {'parts': [current]}
        self.assertTrue(review.apply_suggestion(result, suggestion))
        self.assertEqual(current['display_value'], 'correct')

    def test_rejects_numeric_value_copied_from_another_table_row(self):
        table = {'kind': 'table', 'rows': [
            ['2026', '3 204 744,51'], ['ВСЕГО 3 этап', '3 276 676,77']],
            'cells': [{'row': r, 'column': c, 'text': value,
                       'bbox': [10+c*40, 20+r*25, 50+c*40, 45+r*25]}
                      for r, values in enumerate([['2026', '3 204 744,51'], ['ВСЕГО 3 этап', '3 276 676,77']])
                      for c, value in enumerate(values)],
            'provenance': [{'page_no': 1, 'bbox': {'l': 10, 't': 20, 'r': 190, 'b': 90}}]}
        raw = {'action': 'replace_cell', 'target_index': 0, 'row': 1, 'column': 1,
               'target_cell_id': review._cell_id(table, 1, 1), 'bbox': [250, 450, 450, 700],
               'proposed': '3 204 744,51'}
        self.assertEqual(review._normalise_suggestions([raw], 1, [table], [table], 'parts',
                                                       {'width': 200, 'height': 100}), [])

    def test_rejects_annual_value_copied_into_cumulative_total_row(self):
        rows = [['3 этап, 2026 г.', '3 204 744,51'],
                ['ВСЕГО 3 этап', '3 276 676,77']]
        table = {'kind': 'table', 'rows': rows,
                 'cells': [{'row': r, 'column': c, 'text': value,
                            'bbox': [10 + c*80, 20 + r*30, 90 + c*80, 45 + r*30]}
                           for r, row in enumerate(rows) for c, value in enumerate(row)],
                 'provenance': [{'page_no': 1, 'bbox': {'l': 10, 't': 20, 'r': 170, 'b': 80}}]}
        raw = {'action': 'replace_cell', 'target_index': 0, 'row': 1, 'column': 1,
               'target_cell_id': review._cell_id(table, 1, 1), 'bbox': [450, 450, 900, 700],
               'proposed': '3 204 744,51'}
        self.assertEqual(review._normalise_suggestions([raw], 1, [table], [table], 'parts',
                                                       {'width': 200, 'height': 100}), [])

    def test_rejects_replacing_numeric_column_index_with_prose(self):
        table = {'kind': 'table', 'rows': [['', '6']],
                 'cells': [{'row': 0, 'column': 0, 'bbox': [10, 20, 50, 45]},
                           {'row': 0, 'column': 1, 'bbox': [50, 20, 90, 45]}],
                 'provenance': [{'page_no': 1, 'bbox': {'l': 10, 't': 20, 'r': 190, 'b': 90}}]}
        raw = {'action': 'replace_cell', 'target_index': 0, 'row': 0, 'column': 1,
               'target_cell_id': review._cell_id(table, 0, 1), 'bbox': [250, 200, 450, 450],
               'proposed': 'основная заработная плата'}
        self.assertEqual(review._normalise_suggestions([raw], 1, [table], [table], 'parts',
                                                       {'width': 200, 'height': 100}), [])

    def test_rejects_single_pass_change_to_article_code(self):
        table = {'kind': 'table', 'rows': [['Статья калькуляции :C0000']],
                 'cells': [{'row': 0, 'column': 0, 'bbox': [10, 20, 90, 45]}],
                 'provenance': [{'page_no': 1}]}
        raw = {'action': 'replace_cell', 'target_index': 0, 'row': 0, 'column': 0,
               'target_cell_id': review._cell_id(table, 0, 0), 'bbox': [100, 200, 900, 450],
               'proposed': 'Статья калькуляции 0600'}
        suggestions = review._normalise_suggestions([raw], 1, [table], [table], 'parts',
                                                     {'width': 100, 'height': 100})
        self.assertEqual(len(suggestions), 1)
        self.assertTrue(suggestions[0]['numeric_change'])
        self.assertFalse(suggestions[0]['numeric_verified'])

    def test_cell_change_requires_exact_cell_identity_and_matching_bbox(self):
        table = {'kind': 'table', 'rows': [['old']],
                 'cells': [{'row': 0, 'column': 0, 'bbox': [20, 10, 80, 30]}],
                 'provenance': [{'page_no': 1}]}
        raw = {'action': 'replace_cell', 'target_index': 0, 'row': 0, 'column': 0,
               'target_cell_id': review._cell_id(table, 0, 0), 'bbox': [100, 100, 300, 300],
               'proposed': 'new'}
        self.assertEqual(review._normalise_suggestions([raw], 1, [table], [table], 'parts',
                                                       {'width': 100, 'height': 100}), [])

    def test_cell_identity_survives_inserted_row_before_apply(self):
        table = {'kind': 'table', 'rows': [['header'], ['target']],
                 'cells': [{'row': 0, 'column': 0, 'text': 'header', 'bbox': [10, 10, 90, 20]},
                           {'row': 1, 'column': 0, 'text': 'target', 'bbox': [10, 30, 90, 40]}],
                 'provenance': [{'page_no': 1, 'bbox': {'l': 10, 't': 10, 'r': 90, 'b': 40}}]}
        suggestion = {'id': 'stable-cell', 'action': 'replace_cell', 'page_no': 1,
                      'target_scope': 'parts', 'target_kind': 'table', 'target_index': 0,
                      'target_signature': review.target_signature(table),
                      'target_bbox': review._box(table), 'target_cell_id': review._cell_id(table, 1, 0),
                      'row': 1, 'column': 0, 'original': 'target', 'proposed': 'corrected',
                      'bbox_normalized': [125, 750, 900, 990], 'evidence_verified': True,
                      'source_verified': True}
        table['rows'].insert(1, ['new row'])
        for cell in table['cells']:
            if cell['row'] >= 1:
                cell['row'] += 1
        table['cells'].insert(1, {'row': 1, 'column': 0, 'text': 'new row',
                                  'bbox': [10, 20, 90, 30]})
        result = {'parts': [table]}
        self.assertTrue(review.apply_suggestion(result, suggestion))
        self.assertEqual(table['rows'], [['header'], ['new row'], ['corrected']])

    def test_model_payload_carries_stable_cell_id_geometry_and_spans(self):
        table = {'kind': 'table', 'rows': [['merged']],
                 'cells': [{'row': 0, 'column': 0, 'text': 'merged', 'row_span': 2,
                            'col_span': 3, 'bbox': [10, 20, 30, 40]}]}
        page, _, _, _ = review._text_parts([table], 1, {'width': 100, 'height': 100})
        cell = page[0]['cells'][0]
        self.assertEqual(cell['bbox'], [100, 200, 300, 400])
        self.assertEqual((cell['row_span'], cell['col_span']), (2, 3))
        self.assertEqual(cell['cell_id'], review._cell_id(table, 0, 0))
        self.assertEqual(review._text_parts([table], 1, {'width': 100, 'height': 100})[0][0]['cells'][0]['cell_id'], cell['cell_id'])

    def test_wide_table_crops_split_columns_and_keep_row_context(self):
        from PIL import Image
        rows = [['name'] + [f'c{i}' for i in range(16)], ['item'] + [str(i) for i in range(16)]]
        cells = []
        for row in range(2):
            for column in range(17):
                left = column * 50
                cells.append({'row': row, 'column': column,
                              'bbox': [left, row * 30, left + 45, row * 30 + 25]})
        table = {'kind': 'table', 'rows': rows, 'cells': cells,
                 'provenance': [{'page_no': 1, 'bbox': {'l': 0, 't': 0, 'r': 850, 'b': 60}}]}
        crops = review._wide_table_crops(Image.new('RGB', (1700, 120)), [table],
                                         {'width': 850, 'height': 60})
        self.assertEqual(len(crops), 4)
        self.assertEqual(crops[0][0], [0, 1, 2, 3])
        self.assertEqual(crops[1][0][:2], [0, 1])
        self.assertTrue(all(crop.width > 0 and crop.height > 0 for _, crop in crops))

    def test_missing_numbered_column_header_is_proposed_for_visual_confirmation(self):
        table = {'kind': 'table', 'rows': [['', '2', '3', '4']],
                 'cells': [{'row': 0, 'column': c, 'text': value, 'bbox': [c*20, 0, (c+1)*20, 10]}
                           for c, value in enumerate(['', '2', '3', '4'])],
                 'provenance': [{'page_no': 1, 'bbox': {'l': 0, 't': 0, 'r': 80, 'b': 10}}]}
        page_parts, _, source_parts, _ = review._text_parts([table], 1, {'width': 80, 'height': 10})
        suggestions = review._numbered_header_gap_suggestions(page_parts, source_parts, 1,
                                                               {'width': 80, 'height': 10}, 'parts', [])
        self.assertEqual(len(suggestions), 1)
        self.assertEqual((suggestions[0]['row'], suggestions[0]['column'], suggestions[0]['proposed']), (0, 0, '1'))
        self.assertFalse(suggestions[0]['numeric_verified'])

    def test_unverified_cell_suggestion_cannot_be_applied(self):
        result = {'parts': [{'kind': 'table', 'rows': [['old']],
                            'cells': [{'row': 0, 'column': 0, 'text': 'old'}]}]}
        suggestion = {'action': 'replace_cell', 'row': 0, 'column': 0,
                      'target_index': 0, 'target_kind': 'table', 'page_no': 1,
                      'original': 'old', 'proposed': 'new'}
        self.assertFalse(review.apply_suggestion(result, suggestion))
        self.assertEqual(result['parts'][0]['rows'][0][0], 'old')

    def test_unverified_visual_text_suggestion_cannot_be_applied(self):
        part = {'kind': 'text', 'text': 'old', 'provenance': [
            {'page_no': 1, 'bbox': {'l': 10, 't': 10, 'r': 50, 'b': 20}}]}
        result = {'parts': [part]}
        suggestion = {'action': 'replace_text', 'target_index': 0, 'target_scope': 'parts',
                      'target_kind': 'text', 'page_no': 1, 'target_signature': review.target_signature(part),
                      'target_bbox': review._box(part), 'original': 'old', 'proposed': 'new'}
        self.assertFalse(review.apply_suggestion(result, suggestion))
        self.assertEqual(part['text'], 'old')

    def test_accepted_text_edit_can_be_undone(self):
        part = {'kind': 'text', 'text': 'old', 'provenance': [
            {'page_no': 1, 'bbox': {'l': 10, 't': 10, 'r': 50, 'b': 20}}]}
        suggestion = {'id': 'edit1', 'action': 'replace_text', 'target_index': 0,
                      'target_scope': 'parts', 'target_kind': 'text', 'page_no': 1,
                      'target_signature': review.target_signature(part),
                      'target_bbox': review._box(part), 'original': 'old',
                      'proposed': 'new', 'accepted_proposed': 'new', 'status': 'accepted',
                      'evidence_verified': True, 'source_verified': True}
        result = {'parts': [part]}
        self.assertTrue(review.apply_suggestion(result, suggestion, 'new'))
        self.assertTrue(review.revert_suggestion(result, suggestion))
        self.assertEqual(part['text'], 'old')

    def test_accepted_cell_edit_can_be_undone(self):
        table = {'kind': 'table', 'rows': [['old']], 'cells': [
            {'row': 0, 'column': 0, 'text': 'old', 'bbox': [10, 10, 50, 20]}],
            'provenance': [{'page_no': 1, 'bbox': {'l': 10, 't': 10, 'r': 50, 'b': 20}}]}
        suggestion = {'id': 'edit2', 'action': 'replace_cell', 'target_index': 0,
                      'target_scope': 'parts', 'target_kind': 'table', 'page_no': 1,
                      'target_signature': review.target_signature(table),
                      'target_bbox': review._box(table), 'target_cell_id': review._cell_id(table,0,0),
                      'row': 0, 'column': 0, 'original': 'old', 'proposed': 'new',
                      'accepted_proposed': 'new', 'status': 'accepted',
                      'bbox_normalized': [250, 250, 500, 500], 'evidence_verified': True}
        suggestion['source_verified'] = True
        result = {'parts': [table]}
        self.assertTrue(review.apply_suggestion(result, suggestion, 'new'))
        self.assertTrue(review.revert_suggestion(result, suggestion))
        self.assertEqual(table['rows'][0][0], 'old')

    def test_numeric_edit_requires_independent_crop_confirmation(self):
        from PIL import Image
        payload = {'choices': [{'message': {'content': json.dumps({'observed':'0600','confirmed':True})}}],
                   'usage': {'cost_rub': .002}}
        suggestion = {'action':'replace_cell','proposed':'0600','numeric_change':True,
                      'numeric_bbox_normalized':[250,250,500,500]}
        with patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(payload).encode())):
            verified, cost = review._verify_numeric_suggestions([suggestion], Image.new('RGB',(200,100)),
                                                                 {'width':200,'height':100},'test-model','test-key')
        self.assertEqual(len(verified),1)
        self.assertTrue(verified[0]['numeric_verified'])
        self.assertTrue(verified[0]['source_verified'])
        self.assertEqual(cost,.002)

    def test_numeric_edit_is_retained_unapplied_when_second_read_disagrees(self):
        from PIL import Image
        payload = {'choices': [{'message': {'content': json.dumps({'observed':'0300','confirmed':False})}}]}
        suggestion = {'action':'replace_cell','proposed':'0600','numeric_change':True,
                      'numeric_bbox_normalized':[250,250,500,500]}
        with patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(payload).encode())):
            verified, _ = review._verify_numeric_suggestions([suggestion], Image.new('RGB',(200,100)),
                                                               {'width':200,'height':100},'test-model','test-key')
        self.assertEqual(len(verified), 1)
        self.assertEqual(verified[0]['status'], 'verification_failed')

    def test_text_edit_requires_literal_second_read_of_original_crop(self):
        from PIL import Image
        payload = {'choices': [{'message': {'content': json.dumps({'observed': 'Correct text'})}}],
                   'usage': {'cost_rub': .003}}
        suggestion = {'action':'replace_text','proposed':'Correct text','numeric_change':False,
                      'numeric_bbox_normalized':[100,100,500,300]}
        with patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(payload).encode())):
            verified, cost = review._verify_text_suggestions([suggestion], Image.new('RGB',(400,200)),
                                                              {'width':400,'height':200},'test-model','test-key')
        self.assertEqual(len(verified),1)
        self.assertTrue(verified[0]['source_verified'])
        self.assertEqual(cost,.003)

    def test_text_edit_is_retained_unapplied_when_literal_second_read_disagrees(self):
        from PIL import Image
        payload = {'choices': [{'message': {'content': json.dumps({'observed': 'Different text'})}}]}
        suggestion = {'action':'replace_text','proposed':'Correct text','numeric_change':False,
                      'numeric_bbox_normalized':[100,100,500,300]}
        with patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(payload).encode())):
            verified, _ = review._verify_text_suggestions([suggestion], Image.new('RGB',(400,200)),
                                                            {'width':400,'height':200},'test-model','test-key')
        self.assertEqual(len(verified), 1)
        self.assertEqual(verified[0]['status'], 'verification_failed')

    def test_image_structure_must_match_table_dimensions_and_merges(self):
        table = {'kind': 'table', 'rows': [['A', 'B'], ['C', 'D']],
                 'cells': [{'row': r, 'column': c, 'row_span': 2 if (r, c) == (0, 0) else 1, 'col_span': 1}
                           for r in range(2) for c in range(2)],
                 'provenance': [{'page_no': 1, 'bbox': {'l': 10, 't': 20, 'r': 90, 'b': 80}}]}
        structure = {'bbox': [100, 200, 900, 800], 'row_count': 2, 'column_count': 2,
                     'row_edges': [200, 500, 800], 'column_edges': [100, 500, 900],
                     'merged_cells': [[0, 0, 2, 1]]}
        verified = review._verify_page_structure([structure], [table], [table], {'width': 100, 'height': 100})
        self.assertEqual(verified['status'], 'matched')
        self.assertEqual(verified['matched_tables'], {0: verified['tables'][0]['table_id']})

        wrong_grid = dict(structure, row_count=3, row_edges=[200, 400, 600, 800])
        rejected = review._verify_page_structure([wrong_grid], [table], [table], {'width': 100, 'height': 100})
        self.assertEqual(rejected['status'], 'review')
        self.assertEqual(rejected['unmatched_extracted_tables'], [0])
        cell_edit = {'action': 'replace_cell', 'target_index': 0, 'status': 'pending'}
        review._gate_structural_suggestions([cell_edit], rejected, [table], {'width': 100, 'height': 100})
        self.assertEqual(cell_edit['status'], 'pending')
        self.assertFalse(cell_edit['structure_verified'])

    def test_raster_grid_rejects_missing_internal_rule_and_hidden_split(self):
        from PIL import ImageDraw
        image = Image.new('RGB', (200, 200), 'white')
        draw = ImageDraw.Draw(image)
        for edge in (10, 100, 190):
            draw.line((10, edge, 190, edge), fill='black', width=2)
            draw.line((edge, 10, edge, 190), fill='black', width=2)
        part = {'rows': [['a','b'],['c','d']], 'cells': [
            {'row':r,'column':c,'bbox':[10+c*90,10+r*90,100+c*90,100+r*90]}
            for r in range(2) for c in range(2)]}
        self.assertTrue(review._raster_grid_matches(image, part, {'width':200,'height':200}))
        blank = Image.new('RGB', (200,200), 'white')
        self.assertFalse(review._raster_grid_matches(blank, part, {'width':200,'height':200}))
        merged = {'rows': [['a'],['c']], 'cells': [
            {'row':r,'column':0,'bbox':[10,10+r*90,190,100+r*90]} for r in range(2)]}
        self.assertFalse(review._raster_grid_matches(image, merged, {'width':200,'height':200}))

    def test_numeric_read_rejects_different_decimal_position(self):
        payload = {'choices':[{'message':{'content':json.dumps({'observed':'1.23','confirmed':True})}}]}
        suggestion = {'action':'replace_cell','proposed':'12.3','numeric_change':True,
                      'numeric_bbox_normalized':[100,100,500,500]}
        with patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(payload).encode())):
            verified, _ = review._verify_numeric_suggestions([suggestion], Image.new('RGB',(200,200)),
                {'width':200,'height':200},'test-model','test-key')
        self.assertEqual(verified[0]['status'], 'verification_failed')

    def test_visual_additions_require_independent_exact_read_before_apply(self):
        from PIL import Image
        suggestion = {'id': 'add-text', 'page_no': 1, 'action': 'add_text', 'target_scope': 'parts',
                      'bbox_normalized': [100, 100, 800, 300], 'proposed': 'Подтверждённая строка',
                      'numeric_change': False}
        payload = {'choices': [{'message': {'content': json.dumps({'observed': 'Подтверждённая строка'})}}],
                   'usage': {'cost_rub': .002}}
        with patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(payload).encode())):
            verified, cost = review._verify_text_suggestions([suggestion], Image.new('RGB', (500, 300)),
                {'width': 500, 'height': 300}, 'test-model', 'test-key')
        self.assertTrue(verified[0]['source_verified'])
        self.assertEqual(cost, .002)
        result = {'parts': [], 'visual_layout': {'pages': {'1': {'size': {'width': 500, 'height': 300}}}}}
        self.assertTrue(review.apply_suggestion(result, verified[0]))

        unverified = dict(suggestion, id='unverified', source_verified=False)
        self.assertFalse(review.apply_suggestion({'parts': []}, unverified))
        altered = dict(verified[0], id='altered')
        self.assertFalse(review.apply_suggestion(result, altered, 'Different text'))


if __name__ == '__main__':
    unittest.main()
