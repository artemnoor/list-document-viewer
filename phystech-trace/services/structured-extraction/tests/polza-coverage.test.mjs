import test from 'node:test';
import assert from 'node:assert/strict';
import {buildGroundedContext,callPolzaForExtraction} from '../lib/extraction/polza-ai.mjs';
const parsed = {document_id:'coverage',title:'Договор',parts:Array.from({length:200},(_,i)=>({kind:'paragraph',id:`p${i}`,text:`Пункт ${i}: ${'условие '.repeat(30)}`})),logical_tables:[{id:'items',headers:['Наименование','Сумма'],rows:Array.from({length:30},(_,i)=>({row_id:`row${i}`,cells:[{id:`name${i}`,column:0,text:`Работа ${i}`},{id:`sum${i}`,column:1,text:String(i+1)}]}))}]};
test('every middle row and late paragraph remains available for semantic analysis',()=>{
 const context=buildGroundedContext(parsed);
 assert.equal(context.tables[0].rows.length,30);
 assert.ok(context.source_elements.some(e=>e.text.includes('Пункт 199:')));
});
test('bounded extraction visits every source and preserves exact middle-row value',async()=>{
 const seen=new Set(); let calls=0;
 const result=await callPolzaForExtraction(parsed,{POLZA_API_KEY:'offline',POLZA_FETCH:async(_,init)=>{
 calls++; const context=JSON.parse(JSON.parse(init.body).messages[1].content);
 assert.ok(JSON.stringify(context).length<=34000);
 for(const e of context.source_elements) seen.add(e.text);
 for(const t of context.tables) for(const r of t.rows) for(const c of r.cells) seen.add(c.text);
 return new Response(JSON.stringify({choices:[{finish_reason:'stop',message:{content:JSON.stringify({document_type:'contract',classification_confidence:.9,field_candidates:[],table_mappings:[]})}}]}));
 }});
 assert.ok(calls>1); assert.ok(seen.has('Работа 15')); assert.ok([...seen].some(t=>t.includes('Пункт 199:')));
 assert.equal(result.called,true);
});

test('all native PDF XLSX DOCX available elements survive bounded planning',async()=>{
 const {readFile}=await import('node:fs/promises');
 const {adaptDocumentParserResult}=await import('../lib/parser/document-parser-adapter.mjs');
 const {buildGroundedContexts}=await import('../lib/extraction/polza-ai.mjs');
 for(const kind of ['pdf','xlsx','docx']) {
  const input=JSON.parse(await readFile(new URL(`./fixtures/document-parser-native-${kind}.analysis.json`,import.meta.url),'utf8'));
  const source=adaptDocumentParserResult(input); const contexts=buildGroundedContexts(input);
  const texts=new Map();
  const add=(id,text)=>texts.set(id,[...(texts.get(id)??[]),text]);
  for(const context of contexts) {
   assert.ok(JSON.stringify(context).length<=34000);
   for(const e of context.source_elements) add(e.source_element_id,e.text);
   for(const t of context.tables){for(const h of t.headers) for(const id of h.source_element_ids) add(id,h.label);for(const r of t.rows) for(const c of r.cells) add(c.source_element_id,c.text);}
  }
  for(const e of source.elements.filter(e=>e.source_available!==false&&e.text.trim())) assert.ok(texts.has(e.id),`${kind}: ${e.id} omitted`);
 }
});
test('failed LLM fragments stay failures with retained checkpoints and no rules fallback',async()=>{
 let calls=0;
 await assert.rejects(callPolzaForExtraction({document_id:'broken',parts:[{id:'p',kind:'paragraph',text:'Договор Д-1'}]},{POLZA_API_KEY:'offline',POLZA_FETCH:async()=>{
 calls++; return new Response(JSON.stringify({choices:[{message:{content:'{broken'}}]}));
 }}),error=>error.code==='POLZA_INVALID_JSON'&&error.details.failed_fragment===0&&error.details.unprocessed_fragments===1);
 assert.equal(calls,2);
});

test('extraction entrypoint retains checkpoints and marks grounded ambiguity for review',async()=>{
 const {extractStructuredDocument}=await import('../lib/extraction/structured-extraction.mjs');
 const input={document_id:'ambiguity',title:'Договор',parts:[{id:'p',kind:'paragraph',text:'Договор А-1. Договор Б-2.'}]};
 const context=buildGroundedContext(input); const id=context.source_elements[0].source_element_id;
 const llm=await callPolzaForExtraction(input,{POLZA_API_KEY:'offline',POLZA_FETCH:async()=>new Response(JSON.stringify({choices:[{message:{content:JSON.stringify({document_type:'contract',classification_confidence:.9,field_candidates:[{field_key:'contract_number',source_element_id:id,source_value:'А-1',confidence:.9},{field_key:'contract_number',source_element_id:id,source_value:'Б-2',confidence:.9}],table_mappings:[]})}}]}))});
 llm.mapping_conflicts=[{kind:'classification',values:['contract','act']}];
 const result=extractStructuredDocument(input,{mode:'llm_assisted',llm});
 assert.equal(result.extraction_engine.llm.usage.quality_analysis.fragment_count,1);
 assert.equal(result.classification.status,'review');
 assert.equal(result.fields.contract_number.status,'review');
 assert.equal(result.fields.contract_number.value,null);
 assert.ok(result.review_required.some(r=>r.path==='classification'));
 assert.equal(result.fields.contract_number.conflict.llm.length,2);
});

test('repair includes malformed response usage and preserves unknown expense explicitly',async()=>{
 for(const missing of [false,true]) {
  let calls=0;
  const result=await callPolzaForExtraction({document_id:'usage',parts:[{kind:'paragraph',id:'p',text:'Договор Д-1'}]},{POLZA_API_KEY:'offline',POLZA_FETCH:async()=>{
   calls++;
   return new Response(JSON.stringify({...(missing&&calls===1?{}:{usage:{prompt_tokens:calls*10,completion_tokens:calls,cost:calls*.1}}),choices:[{message:{content:calls===1?'{broken':JSON.stringify({document_type:'contract',classification_confidence:.9,field_candidates:[],table_mappings:[]})}}]}));
  }});
  assert.equal(result.model_calls,2);
  assert.equal(result.usage.prompt_tokens,missing?null:30);
  assert.equal(result.usage.known_usage.prompt_tokens,missing?20:30);
  assert.equal(result.usage.completion_tokens,missing?null:3);
  assert.equal(result.usage.usage_complete,!missing);
  assert.equal(result.usage.unknown_attempts,missing?1:0);
  assert.equal(result.model_attempts[0].raw_output,'{broken');
  assert.ok(result.duration_ms>=0);
 }
});
