function decodeBase64Url(segment) {
  if (!/^[A-Za-z0-9_-]+$/.test(segment)) throw new Error("invalid base64url");
  const base64 = segment.replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));
}

function hasAudience(audience, expected) {
  return audience === expected || Array.isArray(audience) && audience.includes(expected);
}

export async function verifySessionJwt(token, secret, { issuer, audience, now = Math.floor(Date.now() / 1000) } = {}) {
  if (typeof token !== "string" || typeof secret !== "string" || !secret || !issuer || !audience) return null;
  const segments = token.split(".");
  if (segments.length !== 3) return null;
  try {
    const header = JSON.parse(new TextDecoder().decode(decodeBase64Url(segments[0])));
    if (header.alg !== "HS256" || header.typ && header.typ !== "JWT") return null;
    const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["verify"]);
    if (!await crypto.subtle.verify("HMAC", key, decodeBase64Url(segments[2]), new TextEncoder().encode(`${segments[0]}.${segments[1]}`))) return null;
    const claims = JSON.parse(new TextDecoder().decode(decodeBase64Url(segments[1])));
    if (claims.iss !== issuer || !hasAudience(claims.aud, audience)) return null;
    if (typeof claims.sub !== "string" || !claims.sub.trim() || typeof claims.email !== "string" || !claims.email.includes("@")) return null;
    if (!Number.isFinite(claims.exp) || claims.exp <= now) return null;
    if (claims.nbf !== undefined && (!Number.isFinite(claims.nbf) || claims.nbf > now)) return null;
    return claims;
  } catch {
    return null;
  }
}
