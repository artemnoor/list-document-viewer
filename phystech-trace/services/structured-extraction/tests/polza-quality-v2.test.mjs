import test from 'node:test';
import assert from 'node:assert/strict';
import {buildGroundedContexts,buildGroundedContext,callPolzaForExtraction} from '../lib/extraction/polza-ai.mjs';
import {extractStructuredDocument} from '../lib/extraction/structured-extraction.mjs';
const empty={document_type:'contract',classification_confidence:.9,field_candidates:[],table_mappings:[]};
const respond=value=>new Response(JSON.stringify({choices:[{message:{content:JSON.stringify(value)}}]}));
test('one table descriptor per table in each request preserves every row',()=>{
 const input={document_id:'packing',logical_tables:[{id:'t',headers:['Позиция','Сумма'],rows:Array.from({length:80},(_,i)=>({row_id:`r${i}`,cells:[{column:0,text:`Работа ${i}`},{column:1,text:String(i)}]}))}]};
 const contexts=buildGroundedContexts(input);const rows=[];
 for(const c of contexts){assert.equal(new Set(c.tables.map(t=>t.table_id)).size,c.tables.length);for(const t of c.tables)rows.push(...t.rows.map(r=>r.row_id));assert.ok(JSON.stringify(c).length<=33000);}
 assert.equal(new Set(rows).size,80);
});
test('equivalent grounded dates do not become false field conflicts',()=>{
 const input={document_id:'dates',title:'Договор',parts:[{id:'p',kind:'paragraph',text:'Дата договора: 15.03.2026\nДата договора: 2026-03-15'}]};
 const id=buildGroundedContext(input).source_elements[0].source_element_id;
 const llm={...empty,field_candidates:['15.03.2026','2026-03-15'].map(source_value=>({field_key:'contract_date',source_element_id:id,source_value,confidence:.9}))};
 const result=extractStructuredDocument(input,{mode:'llm_assisted',llm});assert.equal(result.fields.contract_date.status,'extracted');assert.equal(result.fields.contract_date.value,'2026-03-15');
});
test('ungrounded duplicate cannot hide a later valid field candidate or create ambiguity',()=>{
 const input={document_id:'refs',title:'Договор',parts:[{id:'p',kind:'paragraph',text:'Идентификатор документа А-1'}]};
 const id=buildGroundedContext(input).source_elements[0].source_element_id;
 const candidates=[{field_key:'contract_number',source_element_id:'does-not-exist',source_value:'fake',confidence:1},{field_key:'contract_number',source_element_id:id,source_value:'А-1',confidence:.9}];
 const result=extractStructuredDocument(input,{mode:'llm_assisted',llm:{...empty,field_candidates:candidates}});
 assert.equal(result.fields.contract_number.value,'А-1');assert.equal(result.fields.contract_number.status,'extracted');
});

test('caller context and output limits are enforced before transport',async()=>{
 const input={document_id:'limits',parts:Array.from({length:25},(_,i)=>({kind:'paragraph',id:`p${i}`,text:`Раздел ${i}: ${'Договор '.repeat(100)}`}))};let calls=0;
 const result=await callPolzaForExtraction(input,{POLZA_API_KEY:'offline',POLZA_CONTEXT_MAX_CHARS:12000,POLZA_MAX_OUTPUT_TOKENS:4000,POLZA_FETCH:async(_,init)=>{
  const body=JSON.parse(init.body);assert.equal(body.max_tokens,4000);assert.ok(body.messages[1].content.length<=12000);calls++;return respond(empty);
 }});assert.ok(calls>1);assert.equal(result.fragment_count,calls);
 await assert.rejects(callPolzaForExtraction(input,{POLZA_API_KEY:'offline',POLZA_MAX_OUTPUT_TOKENS:4097,POLZA_FETCH:()=>{throw Error('must not send');}}),e=>e.code==='POLZA_INVALID_LIMIT');
});
