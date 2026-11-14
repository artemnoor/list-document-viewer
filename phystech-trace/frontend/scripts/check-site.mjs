import assert from "node:assert/strict";

// Read-only checks against the running integrated web server and real Gateway.
const base = (process.argv[2] || "http://127.0.0.1:8080").replace(/\/$/, "");
let checks = 0;
async function get(path, status = 200, type) {
  const response = await fetch(base + path, { redirect: "manual" });
  assert.equal(response.status, status, `${path}: HTTP status`);
  if (type) assert.match(response.headers.get("content-type") || "", type, `${path}: MIME type`);
  checks++;
  return response;
}

for (const path of ["/", "/compare/", "/blog/", "/case-studies/", "/privacy-policy/", "/terms-of-use/"]) {
  const html = await (await get(path, 200, /text\/html/)).text();
  assert.ok(/<!doctype html/i.test(html), `${path}: HTML page`);
  if (!["/privacy-policy/", "/terms-of-use/"].includes(path)) {
    assert.ok(html.includes('/local-assets/site-copy.ru.js'), `${path}: shared product navigation`);
  }
  if (path === "/") {
    assert.ok(html.includes("webflow.c300c877"), "Original Webflow interactions must remain");
    assert.ok(html.includes("ScrollTrigger.min.js"), "Original scroll animations must remain");
    assert.ok(html.includes("lenis.min.js"), "Original scrolling must remain");
    assert.ok(!html.includes("product-patches.js") && !html.includes("landing-product.css"), "Original landing must not load replacement design layers");
  }
}
const app = await (await get("/app/", 200, /text\/html/)).text();
assert.match(app, /id="app"/);
const scripts = [...app.matchAll(/<script[^>]+src="([^"]+)"/g)];
assert.ok(scripts.length, "Workspace must load its application code");
for (const [, path] of scripts) await get(path, 200, /javascript/);
await get("/local-assets/site-copy.ru.js", 200, /javascript/);
await get("/app/brand/phystech-trace.png", 200, /image\/png/);
await get("/app/favicon.svg", 200, /image\/svg\+xml/);
await get("/not-a-real-page", 404);
await get("/app/assets/not-a-real-script.js", 404);
// nginx adds a slash to static directories. It must keep Docker's published port.
const directoryRedirect = await fetch(base + "/compare", { redirect: "manual" });
if (directoryRedirect.status === 301) {
  const target = new URL(directoryRedirect.headers.get("location"), base);
  assert.equal(target.origin, new URL(base).origin);
  assert.equal(target.pathname, "/compare/");
}
for (const path of ["/register", "/logIn", "/logIn/", "/register/index.html"]) {
  const html = await (await get(path, 200, /text\/html/)).text();
  assert.ok(html.includes('id="auth-form"'), `${path}: working account form`);
}
await get("/local-assets/auth.js", 200, /javascript/);
await get("/local-assets/auth.css", 200, /text\/css/);
for (const [path, expected] of [["/app", "/app/"], ["/login", "/logIn"], ["/book-a-demo", "/register"]]) {
  const response = await get(path, 302);
  const target = new URL(response.headers.get("location"), base);
  assert.equal(target.pathname, expected);
  assert.equal(target.origin, new URL(base).origin, "Redirects must preserve the published port");
}
const projects = await (await get("/api/projects", 200, /application\/json/)).json();
assert.ok(Array.isArray(projects.projects));
if (projects.projects.length) {
  const project = projects.projects[0];
  const query = `?project=${encodeURIComponent(project.id)}&tab=verification`;
  const response = await get(`/${query}`, 302);
  const target = new URL(response.headers.get("location"), base);
  assert.equal(target.pathname, "/app/");
  assert.equal(target.origin, new URL(base).origin);
  assert.equal(target.search, query, "Old URLs must preserve project and tab");
  await get(target.pathname + target.search, 200, /text\/html/);
  const saved = await (await get(`/api/projects/${encodeURIComponent(project.id)}`, 200, /application\/json/)).json();
  assert.equal(saved.id, project.id);
}
console.log(`Passed ${checks} HTTP checks against ${base}; Gateway returned ${projects.projects.length} saved projects.`);
