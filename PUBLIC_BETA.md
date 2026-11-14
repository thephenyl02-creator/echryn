# Echryn V1 Public Beta

Echryn is a read-only, evidence-oriented MCP for Instagram Reels, posts, and carousels. V1 is a small rate-limited beta, not an Instagram account connector.

## Connect

MCP server: https://echryn.fenilbuilds.com/mcp/

Connect in a compatible ChatGPT/MCP client and paste a **public** Instagram Reel or post URL. Private, restricted, login-challenged and unavailable content may fail. Never provide Instagram passwords, session cookies, or CSRF tokens to Echryn. V1 does not connect individual users' Instagram accounts.

## Limits

V1 uses an operator-managed Instagram retrieval session, not individual user sessions. New requests are globally limited to **10 per rolling hour**, **50 per UTC calendar day**, and **one active extraction**. These are shared beta-wide limits, not per-user quotas. Counters and leases are stored in one private Google Cloud Storage object and updated atomically with generation preconditions. Storage outage fails closed.

The service can be disabled or limits reduced without notice. The operator session may be challenged or disabled by Instagram; Echryn does not circumvent challenges or bypass access restrictions.

## Content and privacy

Echryn analyzes submitted URLs and related public content. It temporarily downloads media, caches structured results and stores derived frame evidence for approximately 24 hours. Infrastructure logs can include IPs, timing, URLs and errors, with separate hosting-provider retention. Signed media URLs and extraction results are returned to the chatbot provider. Outputs can be incomplete or inaccurate and are not visual proof unless images were inspected.

Echryn is unofficial and not endorsed by Instagram or Meta. Source material belongs to rights holders. Use only on content you may lawfully access. A public link does not itself establish authorization for every automated use. See /privacy and /terms.

## Production configuration

Set on the Cloud Run service, never in Git:

- ECHRYN_V1_LIMITS_ENABLED=true
- ECHRYN_PUBLIC_ENABLED=true
- ECHRYN_V1_HOURLY_LIMIT=10
- ECHRYN_V1_DAILY_LIMIT=50
- ECHRYN_V1_LEASE_SECONDS=360

ECHRYN_FRAME_BUCKET must refer to an existing private bucket writable by the Cloud Run service account. The quota object is control/v1_global_admissions.json. Cloud Run request timeout MUST be less than the extraction lease (360 seconds). Keep max instances at one for V1 to reduce unexpected load; the GCS precondition mechanism protects quota integrity across instances and restarts.

Emergency stop: set ECHRYN_PUBLIC_ENABLED=false on Cloud Run and deploy the new configuration. New extractions on that revision will return 503. Signed URLs previously returned may remain accessible until expiry.

## Source license

Apache License 2.0 (LICENSE), with project attribution (NOTICE). Redistributors must preserve applicable notices. Apache-2.0 does not force end-user display of an Echryn credit or grant unrestricted branding rights.

V2 roadmap: per-user authentication and quotas, independent session isolation, improved video motion understanding, and a new security review.
