import { ensureDemoDocuments, getDocument } from "@/lib/storage";
import { getApiIdentity } from "@/app/api/api-auth";

export async function GET(_request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    await ensureDemoDocuments();
    const { id } = await context.params;
    const user = await getApiIdentity();
    const document = await getDocument(id, user?.userId);
    if (!document) return Response.json({ error: "Документ не найден" }, { status: 404 });
    return Response.json({ parser_json: document.parser_json });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Не удалось прочитать результат парсера";
    return Response.json({ error: message }, { status: 503 });
  }
}
