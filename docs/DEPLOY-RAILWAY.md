# Deploy the demo to Railway

The stack is four services: **Redis**, **api**, **worker**, **frontend**. Railway deploys
`api`/`worker` from `backend/` (same Dockerfile, different start command) and `frontend` from
`frontend/`. The repo is already Railway-ready (`$PORT` handling, Dockerfiles, `railway.json`).

## A) Dashboard (recommended, no CLI login)

1. **New Project → Deploy from GitHub repo** → pick `kliuchnikovv/summer`.
2. **Add Redis:** *New → Database → Add Redis*. Note its service name (e.g. `Redis`).
3. **api service** (Railway creates one from the repo; set its **Root Directory** to `backend`):
   - Variables:
     - `REDIS_URL = ${{Redis.REDIS_URL}}`
     - `OPENROUTER_API_KEY = <your key>`  *(omit to run in mock mode)*
     - `API_KEYS = <key:principal,…>` and `ACCOUNTS = <user:pass:principal:limit,…>` *(override the demo defaults!)*
     - optional tunables: `MAX_UPLOAD_BYTES`, `DAILY_LIMIT`, `MAX_CONCURRENT`, … (see `.env.example`)
   - **Networking → Generate Domain**. Copy the URL (e.g. `https://summer-api-production.up.railway.app`).
4. **worker service:** *New → GitHub Repo → same repo*. Root Directory `backend`.
   - **Settings → Deploy → Start Command:** `python -m app.worker`
   - Variables: `REDIS_URL = ${{Redis.REDIS_URL}}`, `OPENROUTER_API_KEY`, (same as api). No domain.
5. **frontend service:** *New → GitHub Repo → same repo*. Root Directory `frontend`.
   - Variable **and build arg** `NEXT_PUBLIC_API_BASE = <the api domain from step 3>`
     (NEXT_PUBLIC_* is baked at build time — set it before the build; redeploy if you change it).
   - **Networking → Generate Domain** → this is the demo URL.
6. Open the frontend URL, sign in with your `ACCOUNTS` credentials, upload a PDF.

## B) CLI (if you run `railway login`)

```bash
railway login                     # opens a browser (your account)
railway init                      # create/select a project
railway add --database redis      # provision Redis
# then create api / worker / frontend services and set variables, e.g.:
railway variables --set "REDIS_URL=${{Redis.REDIS_URL}}" --set "OPENROUTER_API_KEY=..."
railway up                        # deploy the current directory as a service
```
Multi-service monorepos are fiddlier on the CLI than the dashboard; the dashboard flow above is simpler.

## Notes

- **Mock mode:** without `OPENROUTER_API_KEY` the app still runs (deterministic mock parser/summary).
- **Credentials:** always override `API_KEYS` and `ACCOUNTS` — the in-repo defaults are demo-only.
- **Redis persistence:** Railway's managed Redis handles durability; our compose AOF settings are for local only.
- **CORS** is open (`*`) for the demo; tighten for anything real.
