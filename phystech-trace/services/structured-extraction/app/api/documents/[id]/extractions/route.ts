import { ensureDemoDocuments, getExtractionHistory } from "@/lib/storage";
import { getDocument } from "@/lib/storage";
import { getApiIdentity } from "@/app/api/api-auth";

export async function GET(_request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    await ensureDemoDocuments();
    const { id } = await context.params;
    const user = await getApiIdentity();
    if (!await getDocument(id, user?.userId)) return Response.json({ error: "Документ не найден" }, { status: 404 });
    return Response.json({ history: await getExtractionHistory(id, user?.userId) });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Не удалось прочитать версии";
    return Response.json({ error: message }, { status: 503 });
  }
}
