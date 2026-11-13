declare namespace Cloudflare {
  interface Env {
    DB?: D1Database;
    BUCKET?: R2Bucket;
    POLZA_API_KEY?: string;
    AUTH_SESSION_HMAC_SECRET?: string;
    AUTH_SESSION_ISSUER?: string;
    AUTH_SESSION_AUDIENCE?: string;
  }
}
