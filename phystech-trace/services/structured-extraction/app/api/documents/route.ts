import { ensureDemoDocuments, listDocuments } from "@/lib/storage";
import { getApiIdentity } from "@/app/api/api-auth";

export async function GET() {
  try {
    await ensureDemoDocuments();
    const user = await getApiIdentity();
    return Response.json({ documents: await listDocuments(user?.userId), storage: "Cloudflare D1", user_authenticated: Boolean(user) });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Не удалось прочитать хранилище";
    return Response.json({ error: message, hint: "Проверьте, что миграции D1 применены." }, { status: 503 });
  }
}
