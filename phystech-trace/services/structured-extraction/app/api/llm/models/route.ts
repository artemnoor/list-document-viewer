import { env } from "cloudflare:workers";
import { getApiIdentity } from "@/app/api/api-auth";
import { listPolzaModels, PolzaAiError } from "@/lib/extraction/polza-ai.mjs";

export async function GET() {
  if (!await getApiIdentity()) return Response.json({ error: "Требуется авторизация" }, { status: 401 });
  try {
    const models = await listPolzaModels(env);
    return Response.json({ models: models.map((model: Record<string, unknown>) => ({ id: model.id, object: model.object, owned_by: model.owned_by })) });
  } catch (error) {
    const status = error instanceof PolzaAiError ? error.status : 502;
    return Response.json({ error: error instanceof Error ? error.message : "Polza AI недоступен", code: error instanceof PolzaAiError ? error.code : "POLZA_REQUEST_FAILED" }, { status });
  }
}
