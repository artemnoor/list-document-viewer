import { copyFileSync, mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { demoDocuments } from "../src/linking/demo";
for (const directory of ["fixtures/demo-structured-extraction", "public/demo"]) mkdirSync(directory, { recursive: true });
for (const name of readdirSync("fixtures/upstream-structured-extraction-1.2.0").filter(name => name.endsWith(".json"))) {
  copyFileSync(`fixtures/upstream-structured-extraction-1.2.0/${name}`, `fixtures/demo-structured-extraction/${name}`);
  copyFileSync(`fixtures/upstream-structured-extraction-1.2.0/${name}`, `public/demo/${name}`);
}
for (const document of [demoDocuments[5], ...demoDocuments.slice(6)]) {
  const json = `${JSON.stringify(document, null, 2)}\n`;
  writeFileSync(`fixtures/demo-structured-extraction/${document.document_id}.json`, json);
  writeFileSync(`public/demo/${document.document_id}.json`, json);
}
