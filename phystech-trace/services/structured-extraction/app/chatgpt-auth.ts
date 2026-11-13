import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { env } from "cloudflare:workers";
import { verifySessionJwt } from "@/lib/security/session-jwt.mjs";

export type ChatGPTUser = {
  userId: string;
  displayName: string;
  email: string;
  fullName: string | null;
};

const USER_ID_HEADER = "oai-authenticated-user-id";
const USER_EMAIL_HEADER = "oai-authenticated-user-email";
const SIGN_IN_PATH = "/signin-with-chatgpt";
const SIGN_OUT_PATH = "/signout-with-chatgpt";
const CALLBACK_PATH = "/callback";

export async function getChatGPTUser(): Promise<ChatGPTUser | null> {
  const requestHeaders = await headers();
  // The local Vite auth middleware deletes client-supplied OAI headers, checks
  // its loopback-only sign-in cookie, and adds this marker on the server side.
  if (import.meta.env.DEV && requestHeaders.get("x-app-local-auth") === "1") {
    const userId = requestHeaders.get(USER_ID_HEADER);
    const email = requestHeaders.get(USER_EMAIL_HEADER);
    if (userId === "local_seedy" && email === "seedy@sites.test") {
      return { userId, email, displayName: "Seedy", fullName: "Seedy" };
    }
  }

  // Production does not trust raw oai-authenticated-user-* headers. Only a
  // verifiable host-issued HS256 session can establish a user identity.
  const secret = String(env.AUTH_SESSION_HMAC_SECRET ?? "");
  const token = requestHeaders.get("authorization")?.match(/^Bearer\s+(.+)$/i)?.[1];
  if (!secret || !token) return null;
  const claims = await verifySessionJwt(token, secret, { issuer: String(env.AUTH_SESSION_ISSUER ?? ""), audience: String(env.AUTH_SESSION_AUDIENCE ?? "") });
  if (!claims) return null;
  const fullName = typeof claims.name === "string" ? claims.name : null;
  return { userId: claims.sub, email: claims.email, displayName: fullName ?? claims.email, fullName };
}

export async function requireChatGPTUser(
  returnTo: string,
): Promise<ChatGPTUser> {
  const user = await getChatGPTUser();
  if (user) return user;

  redirect(chatGPTSignInPath(returnTo));
}

export function chatGPTSignInPath(returnTo: string): string {
  const safeReturnTo = safeRelativeReturnPath(returnTo);
  return `${SIGN_IN_PATH}?return_to=${encodeURIComponent(safeReturnTo)}`;
}

export function chatGPTSignOutPath(returnTo = "/"): string {
  const safeReturnTo = safeRelativeReturnPath(returnTo);
  return `${SIGN_OUT_PATH}?return_to=${encodeURIComponent(safeReturnTo)}`;
}

function safeRelativeReturnPath(value: string): string {
  if (!value.startsWith("/") || value.startsWith("//")) return "/";

  let url: URL;
  try {
    url = new URL(value, "https://app.local");
  } catch {
    return "/";
  }
  if (url.origin !== "https://app.local") return "/";
  if (isReservedAuthPath(url.pathname)) return "/";

  return `${url.pathname}${url.search}${url.hash}`;
}

function isReservedAuthPath(pathname: string): boolean {
  return (
    pathname === SIGN_IN_PATH ||
    pathname === SIGN_OUT_PATH ||
    pathname === CALLBACK_PATH
  );
}
