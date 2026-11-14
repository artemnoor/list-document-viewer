import {test} from 'node:test';
import assert from 'node:assert/strict';
import {correctionContext} from '../src/linking/semantic-runner';
import {estimateTokens} from '../src/linking/semantic-plan';
test('correction preserves all source data and bounds a restored diagnostic',()=>{
 const source='SOURCE'.repeat(4900), prompt='JSON';
 const result=correctionContext(source,'x'.repeat(100000),prompt,16000);
 assert.ok(result.startsWith(source));
 assert.ok(estimateTokens(prompt+result)<=16000);
 assert.ok(result.includes('Validation correction:'));
});
