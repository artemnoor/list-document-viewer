import { ensureDemoDocuments, getExtraction } from "@/lib/storage";
import { getApiIdentity } from "@/app/api/api-auth";

export async function GET(_request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    await ensureDemoDocuments();
    const { id } = await context.params;
    const user = await getApiIdentity();
    const extraction = await getExtraction(id, user?.userId);
    if (!extraction) return Response.json({ error: "Версия извлечения не найдена" }, { status: 404 });
    return Response.json({ extraction });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Не удалось прочитать извлечение";
    return Response.json({ error: message }, { status: 503 });
  }
}
