# Echryn Cloudflare Gateway

This Worker is intentionally thin: custom domain/front door, origin API-key injection, and room for D1/R2 caching later.

1. Set `ORIGIN_BASE_URL` in `wrangler.toml`.
2. `npx wrangler secret put ORIGIN_API_KEY`
3. `npx wrangler deploy`

Do not put Instagram session secrets in the Worker. Keep those only on the processor/origin.
