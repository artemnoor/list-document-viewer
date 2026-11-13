import { getChatGPTUser } from "@/app/chatgpt-auth";

export async function getApiIdentity() {
  return getChatGPTUser();
}
