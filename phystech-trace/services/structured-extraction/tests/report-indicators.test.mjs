import test from 'node:test';
import assert from 'node:assert/strict';
import {buildGroundedContext, buildGroundedContexts, callPolzaForExtraction} from '../lib/extraction/polza-ai.mjs';
import {extractStructuredDocument} from '../lib/extraction/structured-extraction.mjs';

test('report preserves arbitrary grounded monetary and nonmonetary indicators', async () => {
 const parsed={document_id:'report-indicators',parts:[{kind:'text',text:'Карточка фактических затрат. Оплата труда: 123,45 руб. Трудоемкость: 42'}]};
 const context=buildGroundedContext(parsed);
 const id=context.source_elements.find(e=>e.text.includes('123,45')).source_element_id;
 const answer={document_type:'kfz_report',classification_confidence:0.99,table_mappings:[],field_candidates:[
 {field_key:'indicator_money:Оплата труда',source_element_id:id,source_value:'123,45 руб.',confidence:0.9},
 {field_key:'indicator_number:Трудоемкость',source_element_id:id,source_value:'42',confidence:0.9},
 {field_key:'indicator_money:Выдуманный',source_element_id:id,source_value:'999,00 руб.',confidence:0.9}]};
 const llm=await callPolzaForExtraction(parsed,{POLZA_API_KEY:'test',POLZA_FETCH:async()=>new Response(JSON.stringify({choices:[{message:{content:JSON.stringify(answer)}}]}))});
 const result=extractStructuredDocument(parsed,{mode:'llm_assisted',llm});
 const money=result.indicators.find(i=>i.label==='Оплата труда');
 assert.deepEqual(money?.extracted.value,{amount:'123.45',currency:'RUB'});
 assert.equal(result.indicators.find(i=>i.label==='Трудоемкость')?.extracted.value,'42');
 assert.ok(money.extracted.provenance.source_part_id);
 assert.ok(!result.indicators.some(i=>i.label==='Выдуманный'));
});

test('explicit report role survives unreadable title and unknown model classification', () => {
 const parsed={document_id:'opaque',document_review:{status:'failed'},phystech_trace:{document_role:'kfz'},parts:[{kind:'text',text:'123,45 руб.'}]};
 const result=extractStructuredDocument(parsed,{mode:'llm_assisted',llm:{document_type:'unknown',classification_confidence:0.2,field_candidates:[],table_mappings:[]}});
 assert.equal(result.document_type,'kfz_report');
 assert.equal(result.classification.status,'review');
 assert.ok(result.review_required.some(item=>item.path==='parser.document_review'));
});

test('sparse table cells retain their column positions in the model context', () => {
 const context=buildGroundedContext({document_id:'sparse',logical_tables:[{id:'t',headers:['Period','Unused','Amount'],rows:[{values:['2026','','123,45']}]}]});
 const row=context.tables[0].rows.find(r=>r.cells.some(c=>c.text==='123,45'));
 assert.equal(row.cells.find(c=>c.text==='123,45').column_index,2);
});

test('fragmented tables retain leading label rows when explicit headers are absent', () => {
 const parsed={document_id:'labels',logical_tables:[{id:'t',rows:[{values:['Period','Wages','Total']},...Array.from({length:40},(_,i)=>({values:[String(i),'123.45','x'.repeat(500)]}))]}]};
 const chunks=buildGroundedContexts(parsed,15000).filter(c=>c.tables.length);
 assert.ok(chunks.length>1);
 assert.ok(chunks.every(c=>c.tables[0].leading_rows?.[0].cells.some(cell=>cell.text==='Wages')));
});


test('unrecognized primary documents retain amount, contract and monthly period',()=>{
 const parsed={document_id:'memo',parts:[{kind:'text',text:'Служебная записка'},{kind:'text',text:'Договор: договор AB-17, этап 2.'},{kind:'text',text:'Сумма: 123,45 руб.'},{kind:'text',text:'Период: январь 2026'}]};
 const result=extractStructuredDocument(parsed);
 assert.equal(result.document_type,'unknown');
 assert.deepEqual(result.fields.total_amount?.value,{amount:'123.45',currency:'RUB'});
 assert.equal(result.fields.contract_reference?.value,'AB-17');
 assert.deepEqual(result.fields.reporting_period?.value,{start:'2026-01-01',end:'2026-01-31'});
});

test('a narrative mentioning a contract before a sum does not become its contract identifier',()=>{
 const result=extractStructuredDocument({document_id:'act-label',parts:[{kind:'text',text:'Акт выполненных работ'},{kind:'text',text:'Сопровождение договора за июнь. Сумма: 123,45 руб.'}]});
 assert.equal(result.fields.contract_reference.value,null);
 assert.deepEqual(result.fields.amount_due.value,{amount:'123.45',currency:'RUB'});
});


test('spreadsheet preamble retains project and period above the table header',()=>{
 const parsed={document_id:'preamble',source_extension:'.xlsx',parts:[
  {kind:'cell',sheet:'Sheet1',coordinate:'A1',value:'Проект: AB-17 | Период: Январь 2026'},
  {kind:'cell',sheet:'Sheet1',coordinate:'A3',value:'Вид начисления'},
  {kind:'cell',sheet:'Sheet1',coordinate:'B3',value:'Сумма, руб.'},
  {kind:'cell',sheet:'Sheet1',coordinate:'A4',value:'Основная заработная плата'},
  {kind:'cell',sheet:'Sheet1',coordinate:'B4',value:123.45}
 ]};
 const context=buildGroundedContext(parsed);
 assert.ok(context.source_elements.some(e=>e.text.includes('Проект: AB-17')));
 const result=extractStructuredDocument(parsed);
 assert.deepEqual(result.fields.reporting_period.value,{start:'2026-01-01',end:'2026-01-31'});
 assert.equal(result.fields.reporting_period.provenance.cell_address,'A1');
});

test('primary operation text is retained for linking even when form type is unknown',()=>{
 const result=extractStructuredDocument({document_id:'operation',parts:[{kind:'text',text:'Калибровка лабораторного оборудования для производственных работ'}]});
 assert.ok(Object.values(result.fields).some(field=>field.value==='Калибровка лабораторного оборудования для производственных работ' && field.provenance));
});


test('bare report amounts inherit a single explicit document currency with its source',()=>{
 const parsed={document_id:'currency-report',phystech_trace:{document_role:'kfz'},parts:[{kind:'text',text:'Сметная стоимость: 900,00 руб.'},{kind:'text',text:'Итого: 123,45'}]};
 const ctx=buildGroundedContext(parsed);const id=ctx.source_elements.find(e=>e.text.includes('123,45')).source_element_id;
 const result=extractStructuredDocument(parsed,{mode:'llm_assisted',llm:{document_type:'kfz_report',classification_confidence:.9,field_candidates:[{field_key:'indicator_money:Итого',source_element_id:id,source_value:'123,45',confidence:.9}],table_mappings:[]}});
 assert.equal(result.fields.currency.value,'RUB');assert.ok(result.fields.currency.provenance);
 assert.deepEqual(result.indicators.find(i=>i.key==='indicator_money:Итого').extracted.value,{amount:'123.45',currency:'RUB'});
});


test('an aligned raster grid wins over a logical variant merging different numeric rows',()=>{
 const parsed={document_id:'merged-variant',logical_tables:[{rows:[{values:['Этап 2026','5.00 7.00']},{values:['Этап 2025','5.00']}]}],parts:[{kind:'table',source:'ocr_raster_grid',rows:[['Этап','Итого, руб.'],['Этап 2026','7.00'],['Этап 2025','5.00']],cells:[],provenance:[{page_no:1}]}]};
 const context=buildGroundedContext(parsed);
 const texts=context.tables.flatMap(t=>t.rows.flatMap(r=>r.cells.map(c=>c.text)));
 assert.ok(texts.includes('7.00'));
 assert.ok(!texts.includes('5.00 7.00'));
});


test('act title date and cost-of-services label remain usable without an external call',()=>{
 const result=extractStructuredDocument({document_id:'title-date',parts:[{kind:'text',text:'AKT N 17 OT 28.01.2026'},{kind:'text',text:'Стоимость оказанных услуг: 123,45 руб.'}]});
 assert.equal(result.fields.act_date.value,'2026-01-28');
 assert.deepEqual(result.fields.amount_due.value,{amount:'123.45',currency:'RUB'});
});


test('an amount written in words is not parsed as zero kopecks instead of the explicit total',()=>{
 const result=extractStructuredDocument({document_id:'words',parts:[{kind:'text',text:'Служебная записка'},{kind:'text',text:'Стоимость: семьсот сорок четыре тысячи рублей 00 копеек.'},{kind:'text',text:'Итого: 744 000,00 руб.'}]});
 assert.deepEqual(result.fields.total_amount.value,{amount:'744000.00',currency:'RUB'});
});

test('sum stated after an operation narrative is extracted from its exact numeric suffix',()=>{
 const result=extractStructuredDocument({document_id:'sum-act',parts:[{kind:'text',text:'Акт выполненных работ'},{kind:'text',text:'Административное сопровождение. Сумма по акту: 123,45 руб.'}]});
 assert.deepEqual(result.fields.amount_due.value,{amount:'123.45',currency:'RUB'});
});


test('an invalid model amount cannot erase an unambiguous exact numeric total',()=>{
 const parsed={document_id:'invalid-amount',parts:[{kind:'text',text:'Служебная записка'},{kind:'text',text:'Стоимость: семьсот сорок четыре тысячи рублей 00 копеек.'},{kind:'text',text:'Итого: 744 000,00 руб.'}]};
 const ctx=buildGroundedContext(parsed);const id=ctx.source_elements.find(e=>e.text.startsWith('Стоимость')).source_element_id;
 const result=extractStructuredDocument(parsed,{mode:'llm_assisted',llm:{document_type:'unknown',classification_confidence:.5,field_candidates:[{field_key:'total_amount',source_element_id:id,source_value:'семьсот сорок четыре тысячи рублей 00 копеек.',confidence:.9}],table_mappings:[]}});
 assert.deepEqual(result.fields.total_amount.value,{amount:'744000.00',currency:'RUB'});
 assert.equal(result.fields.total_amount.status,'extracted');
});
