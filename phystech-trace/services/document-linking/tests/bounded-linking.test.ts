import { test } from "node:test";
import assert from "node:assert/strict";
import { analyzeDocumentSet, GEMMA_MODEL } from "../src/linking/llm-matcher";
import { buildEvidenceRegistry } from "../src/linking/evidence-registry";
import { mergeTaskLinks } from "../src/linking/bounded-merge";

const options = { apiKey: "offline-test-only", timeoutMs: 1000, maxCalls: 1000, maxInputTokens: 2400, systemPrompt: "Read source, preserve ambiguity." };
const docs = Array.from({length: 5}, (_, i) => ({ document_id: `doc-${i}`, document_type: "contract", fields: { text: { value: Array.from({length:300}, (_,n)=>`word${i}-${n}`).join(" "), provenance: {document_id:`doc-${i}`,source_text:"source",source_available:true} } }, tables:[{rows:Array.from({length:3},(_,n)=>({row_id:`row-${i}-${n}`,cells:[{value:`middle-${i}-${n}`}]}))}] })) as any[];
function response(value: any) { return new Response(JSON.stringify({model:GEMMA_MODEL, choices:[{message:{content:JSON.stringify(value)}}],usage:{prompt_tokens:10,completion_tokens:5}}),{status:200}); }
function contextOf(user:string) { return JSON.parse(user.slice(user.indexOf("{"))); }
function empty() { return {links:[],unlinked_document_ids:docs.map(d=>d.document_id),context_requests:[],analysis_summary:"No supported relation in visible sources"}; }

test("bounded tasks expose every scalar and text slice across all document pairs without a whole-set reduce",async(t)=>{
  const original=globalThis.fetch; const seen=new Map<string,Map<string,any[]>>(); let relationships=0;
  globalThis.fetch=async(_url,init)=>{
    const body=JSON.parse(String(init?.body)), user=body.messages[1].content;
    assert.ok(Math.ceil((body.messages[0].content.length+user.length)/2)<=options.maxInputTokens,"actual request bounded");
    const context=contextOf(user);
    if(context.document) return response({fragments:[{document_id:context.document.document_id,chunk_index:context.document.chunk_index,summary:"",facts:[],reference_ids:[]}]});
    relationships++; assert.ok(context.documents.length<=2,"no full-set reduction");
    for(const fragment of context.documents) for(const other of context.documents) if(fragment.document_id!==other.document_id){
      const key=`${fragment.document_id}:${other.document_id}`, paths=seen.get(key)??new Map();
      for(const part of fragment.path_values??[]) paths.set(part.path,[...(paths.get(part.path)??[]),part]);
      seen.set(key,paths);
    }
    return response(empty());
  };
  try{
    const result=await analyzeDocumentSet(docs,options); assert.equal(result.complete,true);assert.ok(relationships>=10); t.diagnostic(JSON.stringify({kind:"offline_transport_coverage",documents:docs.length,calls:result.calls,coverage:result.analysisCoverage}));
    for(const doc of docs) for(const other of docs) if(doc!==other){
      const paths=seen.get(`${doc.document_id}:${other.document_id}`); assert.ok(paths);
      for(const ref of buildEvidenceRegistry([doc])){
        const parts=paths!.get(ref.json_path);assert.ok(parts?.length,`missing ${doc.document_id} -> ${other.document_id}: ${ref.json_path}`);
        if(typeof ref.raw_value==="string"&&parts!.some(p=>p.text_offset!==undefined)){
          const unique=[...new Map(parts!.map(p=>[p.text_offset,p])).values()].sort((a,b)=>a.text_offset-b.text_offset);
          assert.equal(unique.map(p=>p.value).join(""),ref.raw_value,"slices reconstruct original scalar");
        } else assert.ok(parts!.some(p=>JSON.stringify(p.value)===JSON.stringify(ref.raw_value)));
      }
    }
  }finally{globalThis.fetch=original;}
});

test("bounded checkpoints resume completed tasks without repeated model calls or premature unlinked claims",async()=>{
  const original=globalThis.fetch; const seen=new Set<string>();let saved:any;
  globalThis.fetch=async(_url,init)=>{
    const user=JSON.parse(String(init?.body)).messages[1].content;assert.equal(seen.has(user),false,"no completed task resubmission");seen.add(user);
    const context=contextOf(user);
    if(context.document)return response({fragments:[{document_id:context.document.document_id,chunk_index:context.document.chunk_index,summary:"",facts:[],reference_ids:[]}]});
    return response(empty());
  };
  try{
    const opts={...options,maxModelCallsPerInvocation:1,onProgress:async(s:any)=>{saved=s;}};
    let result=await analyzeDocumentSet(docs.slice(0,2),opts);assert.equal(result.complete,false);assert.deepEqual(result.unlinkedDocumentIds,[]);
    for(let n=0;!result.complete&&n<300;n++)result=await analyzeDocumentSet(docs.slice(0,2),{...opts,resumeProgress:saved});
    assert.equal(result.complete,true);
  }finally{globalThis.fetch=original;}
});

test("invalid row citation cannot keep confirmed status or masquerade as a valid row match",async()=>{
  const pair=structuredClone(docs.slice(0,2)); for(const doc of pair) doc.fields.text.provenance.source_text=doc.fields.text.value; const refs=buildEvidenceRegistry(pair), original=globalThis.fetch;
  const ids=pair.map(doc=>refs.find(r=>r.document_id===doc.document_id&&r.json_path==="fields.text.value")!.reference_id);
  globalThis.fetch=async()=>response({links:[{relationship_type:"related",source_document_id:pair[0].document_id,target_document_id:pair[1].document_id,source_row_id:"missing-row",target_row_id:"missing-row",evidence:[{source_reference_id:ids[0],target_reference_id:ids[1],signal:"context",explanation:"semantic"}],confidence:0.9,status:"confirmed",explanation:"semantic",conflicts:[],alternatives:[]}],unlinked_document_ids:[],context_requests:[],analysis_summary:"done"});
  try{
    const result=await analyzeDocumentSet(pair,{...options,maxInputTokens:100000,maxEvidenceCorrectionAttempts:0});
    assert.equal(result.links[0]?.status,"review");assert.ok(result.invalidRelationshipDiagnostics.some(d=>d.reason_codes.includes("row_id_not_found")));
  }finally{globalThis.fetch=original;}
});

test("malformed bounded JSON retries only the failed task and preserves raw diagnostic and usage",async()=>{
  const original=globalThis.fetch;let calls=0,saved:any;const users:string[]=[];
  globalThis.fetch=async(_url,init)=>{
    users.push(JSON.parse(String(init?.body)).messages[1].content);calls++;
    if(calls===2)return new Response(JSON.stringify({model:GEMMA_MODEL,choices:[{message:{content:'{"links":['}}],usage:{prompt_tokens:7,completion_tokens:3}}),{status:200});
    return response(empty());
  };
  try{
    const result=await analyzeDocumentSet(docs.slice(0,2),{...options,onProgress:async s=>{saved=s;}});
    assert.equal(result.complete,true);assert.equal(users[1],users[2],"retry original task");assert.notEqual(users[0],users[1],"completed task not repeated");
    assert.ok(saved.model_failures.some((f:any)=>f.raw_response==='{"links":['));
    assert.ok(saved.bounded_tasks.some((t:any)=>t.attempts===2&&t.failures.length===1));
    assert.equal(result.inputTokens,(calls-1)*10+7);assert.equal(result.outputTokens,(calls-1)*5+3);
  }finally{globalThis.fetch=original;}
});

test("permanently malformed bounded task never becomes completed or unlinked and resume does not reset attempts",async()=>{
  const original=globalThis.fetch;let saved:any,calls=0;
  globalThis.fetch=async()=>{calls++;return new Response(JSON.stringify({model:GEMMA_MODEL,choices:[{message:{content:"broken-json"}}],usage:{prompt_tokens:5,completion_tokens:2}}),{status:200});};
  try{
    const opts={...options,onProgress:async(s:any)=>{saved=s;}};
    await assert.rejects(()=>analyzeDocumentSet(docs.slice(0,2),opts));
    assert.equal(calls,2);assert.equal(saved.coverage.completed_tasks,0);assert.equal(saved.bounded_tasks[0].result,undefined);assert.equal(saved.bounded_tasks[0].failures.length,2);
    await assert.rejects(()=>analyzeDocumentSet(docs.slice(0,2),{...opts,resumeProgress:saved}));
    assert.equal(calls,2,"resume must not reset exhausted malformed-task attempts");
  }finally{globalThis.fetch=original;}
});

test("an unsupported citation stays an insufficient-evidence diagnostic rather than no-link finding",async()=>{
  const original=globalThis.fetch;
  globalThis.fetch=async(_url,init)=>{
    const user=JSON.parse(String(init?.body)).messages[1].content, context=contextOf(user);
    if(context.documents.length===1)return response(empty());
    const [source,target]=context.documents;
    return response({...empty(),links:[{relationship_type:"semantic_relation",source_document_id:source.document_id,target_document_id:target.document_id,status:"proposed",confidence:0.8,evidence:[{source_reference_id:"invented",target_reference_id:"invented"}],explanation:"Insufficient source citation"}]});
  };
  try{
    const result=await analyzeDocumentSet(docs.slice(0,2),{...options,maxEvidenceCorrectionAttempts:0});
    assert.equal(result.complete,true);assert.deepEqual(result.links,[]);assert.deepEqual(result.unlinkedDocumentIds,[]);
    assert.ok(result.invalidRelationshipDiagnostics.some(d=>d.reason_codes.includes("evidence_reference_not_found")));
  }finally{globalThis.fetch=original;}
});

test("evidence repair resumes within one-call slices and preserves original proposals", async () => {
  const pair = [{document_id:"a",document_type:"contract",fields:{number:{value:"same",provenance:{document_id:"a",source_text:"same",source_available:true}}}},
    {document_id:"b",document_type:"act",fields:{number:{value:"same",provenance:{document_id:"b",source_text:"same",source_available:true}}}}] as any[];
  const refs=buildEvidenceRegistry(pair).filter(ref=>ref.json_path==="fields.number.value");
  const original=globalThis.fetch;let calls=0,saved:any;
  const proposal={relationship_type:"describes",source_document_id:"a",target_document_id:"b",status:"proposed",confidence:0.8,evidence:[{source_reference_id:"wrong",target_reference_id:"wrong"}]};
  globalThis.fetch=async()=>{calls++; return response(calls===1?{...empty(),links:[proposal]}:{corrections:[{proposal_index:0,action:"replace",link:{...proposal,evidence:[{source_reference_id:refs[0].reference_id,target_reference_id:refs[1].reference_id}]}}]});};
  try{
    const opts={...options,maxInputTokens:10000,maxModelCallsPerInvocation:1,onProgress:async(s:any)=>{saved=s;}};
    let result=await analyzeDocumentSet(pair,opts); assert.equal(calls,1);assert.equal(result.complete,false);
    result=await analyzeDocumentSet(pair,{...opts,resumeProgress:saved});assert.equal(calls,2);assert.equal(result.complete,true);assert.equal(result.links.length,1);
    assert.deepEqual(result.invalidRelationshipDiagnostics[0].proposal,proposal);assert.equal(result.invalidRelationshipDiagnostics[0].resolution,"corrected");
    await assert.rejects(()=>analyzeDocumentSet([{...pair[0],document_type:"changed"},pair[1]],{...opts,resumeProgress:saved}),/Checkpoint/);
  }finally{globalThis.fetch=original;}
});

test("merge preserves different rows, repeated amounts and ambiguous alternatives", () => {
  const base:any={link_id:"1",relationship_type:"fulfills",source_document_id:"a",target_document_id:"b",source_row_id:"row1",target_row_id:"row1",status:"confirmed",confidence:0.9,evidence:[{source:{path:"rows[0].amount",raw_value:100},target:{path:"rows[0].amount",raw_value:100}}],conflicts:[],alternatives:[],explanation:"first"};
  const merged=mergeTaskLinks([base,{...base,link_id:"2",status:"review",alternatives:["another contract"]},{...base,link_id:"3",source_row_id:"row2",target_row_id:"row2"},{...base,link_id:"4",target_document_id:"other-contract"}]);
  assert.equal(merged.length,3);assert.equal(merged[0].status,"review");assert.deepEqual(merged[0].alternatives,["another contract"]);
});

test("insufficient whole-run call budget is rejected before any send with pending tasks saved", async () => {
  const original=globalThis.fetch; let calls=0,saved:any;
  globalThis.fetch=async()=>{calls++;return response(empty());};
  try {
    await assert.rejects(()=>analyzeDocumentSet(docs,{...options,maxCalls:1,onProgress:async(s:any)=>{saved=s;}}),/минимум/);
    assert.equal(calls,0);assert.equal(saved.coverage.completed_tasks,0);assert.ok(saved.coverage.total_tasks>1);
  } finally {globalThis.fetch=original;}
});
