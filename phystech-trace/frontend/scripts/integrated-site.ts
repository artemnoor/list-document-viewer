import { createReadStream, existsSync, statSync } from "node:fs";
import { cp, mkdir, rm } from "node:fs/promises";
import { dirname, extname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import type { IncomingMessage, ServerResponse } from "node:http";
import type { Plugin } from "vite";

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const landing = resolve(frontend, "../landing");
const output = resolve(frontend, "dist");
const aliases = new Set(["/recover", "/book-a-demo"]);
const mime: Record<string, string> = {
  ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
  ".js": "application/javascript; charset=utf-8", ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg", ".webp": "image/webp", ".avif": "image/avif",
  ".gif": "image/gif", ".woff": "font/woff", ".woff2": "font/woff2",
  ".ttf": "font/ttf", ".otf": "font/otf", ".mp4": "video/mp4", ".webm": "video/webm",
};

// Runs before Vite's /app/ base middleware, in both dev and preview.
function siteMiddleware(root: string) {
  return (req: IncomingMessage, res: ServerResponse, next: () => void) => {
    const url = new URL(req.url || "/", "http://localhost");
    let pathname: string;
    try { pathname = decodeURIComponent(url.pathname); }
    catch { res.writeHead(400).end("Bad request"); return; }
    const route = pathname.replace(/\/index\.html$/, "").replace(/\/+$/, "") || "/";
    if (route === "/login") {
      res.writeHead(302, { Location: `/logIn${url.search}` }).end(); return;
    }
    if (route === "/app" && pathname === "/app") {
      res.writeHead(302, { Location: `/app/${url.search}${url.hash}` }).end(); return;
    }
    if (aliases.has(route)) {
      res.writeHead(302, { Location: `/register${url.search}` }).end(); return;
    }
    if (route === "/" && url.searchParams.has("project")) {
      res.writeHead(302, { Location: `/app/${url.search}` }).end(); return;
    }
    if (pathname.startsWith("/app/assets/") && !existsSync(resolve(root, `.${pathname}`))) {
      res.writeHead(404).end("Not found"); return;
    }
    if (pathname.startsWith("/app/") || route === "/api" || pathname.startsWith("/api/") || route === "/health" || pathname.startsWith("/@")) {
      next(); return;
    }
    let file = resolve(root, `.${pathname}`);
    if (!file.startsWith(root + sep) && file !== root) {
      res.writeHead(403).end("Forbidden"); return;
    }
    if (existsSync(file) && statSync(file).isDirectory()) file = resolve(file, "index.html");
    if (!existsSync(file) || !statSync(file).isFile()) {
      res.writeHead(404).end("Not found"); return;
    }
    if (req.method !== "GET" && req.method !== "HEAD") {
      res.writeHead(405, { Allow: "GET, HEAD" }).end(); return;
    }
    res.writeHead(200, { "Content-Type": mime[extname(file)] || "application/octet-stream", "Cache-Control": "no-cache" });
    if (req.method === "HEAD") res.end();
    else createReadStream(file).on("error", () => res.destroy()).pipe(res);
  };
}

export function integratedSite(): Plugin {
  let building = false;
  return {
    name: "phystech-integrated-site",
    configResolved(config) { building = config.command === "build"; },
    async buildStart() {
      if (building) await rm(output, { recursive: true, force: true });
    },
    async closeBundle() {
      if (!building) return;
      await mkdir(output, { recursive: true });
      await cp(landing, output, { recursive: true });
    },
    configureServer(server) { server.middlewares.use(siteMiddleware(landing)); },
    configurePreviewServer(server) { server.middlewares.use(siteMiddleware(output)); },
  };
}
