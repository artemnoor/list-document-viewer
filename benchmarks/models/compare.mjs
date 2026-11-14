// Public synthetic comparison: the same cases, prompt and settings for every model.
import { createHash } from 'node:crypto';
import { writeFileSync, mkdirSync } from 'node:fs';
import { dirname } from 'node:path';

const args = Object.fromEntries(process.argv.slice(2).map(arg => arg.replace(/^--/, '').split('=')));
const key = process.env.POLZA_API_KEY || process.env.POLZA_AI_API_KEY;
if (!key) throw new Error('Set POLZA_API_KEY; only public synthetic data is sent.');
const models = (args.models || 'google/gemma-4-26b-a4b-it,qwen/qwen3.8-27b').split(',');
const repeats = Number(args.repeats || 2);
if (!Number.isInteger(repeats) || repeats < 1 || repeats > 5) throw new Error('repeats must be 1..5');
const system = 'Ты проверяешь финансовый отчёт по первичным документам. Верни только JSON с ключами sources (массив ID), expected (строка с двумя десятичными знаками либо null), status (matched/mismatch/insufficient_data). ID источников — точные латинские метки перед двоеточием, например a, b, act, invoice, registry, jan, credit; не заменяй их названием документа или номером акта. Не считай разные представления одной операции независимыми расходами. При дубле выбери акт, а не счёт или реестр. Данные за чужой период/договор исключаются. При недостаточном покрытии expected=null и sources=[]; недостаток данных не является доказанным расхождением. Валюта RUB. Не добавляй пояснения.';
const cases = [
  { id: 'independent-acts', input: 'Договор DEMO-1, январь 2026. Отчёт: общехозяйственные 120000. a: акт №1, 70000, январь, DEMO-1. b: акт №2, 50000, январь, DEMO-1.', gold: {sources:['a','b'],expected:'120000.00',status:'matched'} },
  { id: 'duplicate-representations', input: 'Договор DEMO-1, январь. Отчёт 100000. act: акт №7 на 100000. invoice: счёт по акту №7 на 100000. registry: строка реестра оплаты акта №7 на 100000. Это одна операция. Не складывай представления.', gold: {sources:['act'],expected:'100000.00',status:'matched'} },
  { id: 'period-and-agreement', input: 'Проверяется DEMO-1 за январь 2026. Отчёт 112500. a: акт DEMO-1 от 20.01.2026 за январь на 100000. june: акт DEMO-1 за июнь на 40000. other: акт OTHER за январь на 12500. Рекламный план на 112500 не является первичкой.', gold: {sources:['a'],expected:'100000.00',status:'mismatch'} },
  { id: 'missing-month', input: 'Отчёт: оплата труда за январь и февраль 2026 — 200000. jan: ведомость зарплаты только за 01.01–31.01.2026 на 100000. Других документов нет. Неизвестно, был ли февральский расход нулевым.', gold: {sources:[],expected:null,status:'insufficient_data'} },
  { id: 'net-vs-vat', input: 'Договор DEMO-1, январь, все документы представлены. Отчёт проверяет стоимость услуги БЕЗ НДС: 100000. a: единственный акт, стоимость без НДС 100000, НДС 20000, всего к оплате 120000. Это три колонки одной операции.', gold: {sources:['a'],expected:'100000.00',status:'matched'} },
  { id: 'negative-adjustment', input: 'Договор DEMO-1, январь. Отчёт 90000. a: акт базовой услуги 100000. credit: отдельный корректировочный акт уменьшает стоимость на 10000; сумма корректировки -10000. Это разные номера операций. Счёт-оферта 150000 — план, не исполнение.', gold: {sources:['a','credit'],expected:'90000.00',status:'matched'} },
];
const results = [];
for (const model of models) {
  for (let repeat = 1; repeat <= repeats; repeat++) {
    for (const item of cases) {
      const messages = [{role:'system',content:system},{role:'user',content:item.input}];
      const started = Date.now();
      const row = {model_requested:model,case_id:item.id,repeat,prompt_sha256:createHash('sha256').update(JSON.stringify(messages)).digest('hex'),expected:item.gold};
      try {
        const response = await fetch('https://polza.ai/api/v1/chat/completions', {method:'POST',headers:{Authorization:`Bearer ${key}`,'Content-Type':'application/json'},body:JSON.stringify({model,messages,temperature:0,max_tokens:2048}),signal:AbortSignal.timeout(90000)});
        const payload = await response.json();
        row.http_status = response.status;
        row.model_returned = payload.model ?? null;
        row.usage = payload.usage ?? null;
        row.finish_reason = payload.choices?.[0]?.finish_reason ?? null;
        const content = payload.choices?.[0]?.message?.content || '';
        row.response = content;
        if (!response.ok) throw new Error(`provider HTTP ${response.status}`);
        const cleaned = content.trim().replace(/^```(?:json)?\s*/i,'').replace(/\s*```$/,'');
        const actual = JSON.parse(cleaned);
        row.actual = actual;
        row.passed = actual.expected === item.gold.expected && actual.status === item.gold.status && JSON.stringify([...(actual.sources || [])].sort()) === JSON.stringify([...item.gold.sources].sort());
      } catch (error) { row.passed = false; row.error = error.message; }
      row.duration_ms = Date.now() - started;
      results.push(row);
    }
  }
}
const output = {dataset:'public-synthetic-model-selection-v2',recorded_at:new Date().toISOString(),scope:'six short Russian text reasoning cases; no OCR, no production-pipeline quality claim',settings:{temperature:0,max_tokens:2048,repeats},cases:cases.map(c=>({id:c.id,input:c.input,gold:c.gold})),summary:models.map(model=>{const rows=results.filter(r=>r.model_requested===model);return {model,calls:rows.length,passed:rows.filter(r=>r.passed).length,correct_amount:rows.filter(r=>r.actual && r.actual.expected===r.expected.expected).length,correct_status:rows.filter(r=>r.actual?.status===r.expected.status).length,correct_sources:rows.filter(r=>r.actual && JSON.stringify([...(r.actual.sources||[])].sort())===JSON.stringify([...r.expected.sources].sort())).length,errors:rows.filter(r=>r.error).length,mean_duration_ms:Math.round(rows.reduce((a,r)=>a+r.duration_ms,0)/rows.length)}}),results};
if (args.output) { mkdirSync(dirname(args.output),{recursive:true});writeFileSync(args.output,JSON.stringify(output,null,2)+'\n'); }
else process.stdout.write(JSON.stringify(output,null,2)+'\n');
