import { mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { linkDocuments } from "../src/linking/link-resolver";
const documents = readdirSync("fixtures/demo-structured-extraction").filter(name => name.endsWith(".json")).map(name => JSON.parse(readFileSync(`fixtures/demo-structured-extraction/${name}`, "utf8")));
const result = await linkDocuments(documents);
mkdirSync("examples", { recursive: true });
writeFileSync("examples/linking-result.json", `${JSON.stringify(result, null, 2)}\n`);
