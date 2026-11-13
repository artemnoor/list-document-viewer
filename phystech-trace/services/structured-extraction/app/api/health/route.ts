import { env } from "cloudflare:workers";
import { polzaAiReadiness } from "@/lib/extraction/polza-ai.mjs";

export async function GET() {
  return Response.json({ status: "ok", service: "kfz-structured-extraction", storage: "Cloudflare D1", parser: "Document Parser JSON only", extraction: "hybrid-rules-and-polza-ai", llm: polzaAiReadiness(env) });
}
