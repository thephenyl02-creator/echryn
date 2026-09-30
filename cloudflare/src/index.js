export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const target = new URL(url.pathname + url.search, env.ORIGIN_BASE_URL);

    const headers = new Headers(request.headers);
    if (env.ORIGIN_API_KEY) headers.set("X-API-Key", env.ORIGIN_API_KEY);

    const upstream = new Request(target, {
      method: request.method,
      headers,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
      redirect: "manual"
    });

    const response = await fetch(upstream);
    const outHeaders = new Headers(response.headers);
    outHeaders.set("X-Echryn-Gateway", "cloudflare");
    return new Response(response.body, {status: response.status, headers: outHeaders});
  }
};
