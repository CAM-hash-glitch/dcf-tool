# DCF Calculator — Web Hosted

Public web tool that computes intrinsic value via DCF for any ticker on Yahoo Finance.
Single FastAPI service, embedded HTML UI, ready to deploy.

**Demo locally:** `pip install -r requirements.txt && uvicorn main:app --reload` → http://localhost:8000

---

## Deploy in 5 minutes — Render (free)

This is the easiest path. Render gives you a free HTTPS URL like `dcf-calculator.onrender.com`.

1. **Push to GitHub.** Create a new GitHub repo (public or private) and push this folder to it:
   ```bash
   git init
   git add .
   git commit -m "initial commit"
   git branch -M main
   git remote add origin https://github.com/<your-username>/dcf-tool.git
   git push -u origin main
   ```

2. **Create the service on Render.**
   - Go to https://dashboard.render.com/blueprints
   - Click **"New Blueprint Instance"**
   - Connect the GitHub repo you just created
   - Render will detect `render.yaml` and set everything up automatically
   - Click **"Apply"**

3. **Wait ~3 minutes** for the first build. You'll get a URL like `https://dcf-calculator.onrender.com`.

That's it. The service is live.

### Free tier caveat

Render free spins down after 15 min idle. First request after wake-up takes ~30s. If you want always-on, upgrade to Starter ($7/mo) or use Fly.io (see below).

---

## Alternative: Fly.io (always-on, ~$0–5/mo)

Fly's free tier covers small apps. Better latency than Render free, no cold starts.

```bash
brew install flyctl              # macOS; see fly.io/docs/hands-on/install-flyctl for others
fly auth signup                  # or `fly auth login`
fly launch                       # answers: yes to deploy, no to postgres, no to redis
```

Fly auto-detects the `Dockerfile` and deploys. You get `https://<app-name>.fly.dev`.

---

## Alternative: Railway (one-click)

1. Push to GitHub (same as Render step 1)
2. Go to https://railway.app/new
3. "Deploy from GitHub repo" → select your repo
4. Railway uses the `Dockerfile` automatically. URL appears in ~2 min.

Railway is ~$5/mo for hobby projects, no free always-on tier as of writing.

---

## What's in this repo

| File | Purpose |
|---|---|
| `main.py` | FastAPI app: routes, rate limiting, validation, embedded HTML UI |
| `dcf.py` | Pure DCF engine + 1-hour TTL cache |
| `requirements.txt` | Pinned Python dependencies |
| `render.yaml` | Render blueprint (auto-deploy config) |
| `Dockerfile` | For Fly, Railway, or any container host |
| `.dockerignore` / `.gitignore` | Standard exclusions |

## Production features baked in

- **Rate limiting:** 30 req/min per IP (sliding window). Returns HTTP 429 with retry hint.
- **Caching:** In-memory TTL cache (1 hour, 1000 entry cap). Cuts Yahoo calls dramatically on repeat lookups.
- **Ticker validation:** Regex-checked before any Yahoo call. Rejects garbage immediately.
- **Health check:** `/healthz` for the platform's uptime monitor (configured in `render.yaml`).
- **Adjustable assumptions:** WACC, terminal growth, projection years available as query params and UI controls.
- **Shareable URLs:** UI updates the address bar with the current ticker + assumptions, so links can be shared.
- **Generic exception handler:** Python tracebacks never leak to users.
- **Auto-generated API docs:** Visit `/docs` for OpenAPI/Swagger UI.

## API

```
GET /api/dcf/{ticker}?wacc=0.09&tg=0.025&years=5
GET /healthz
GET /api/stats
```

Example:
```bash
curl https://your-app.onrender.com/api/dcf/AAPL
curl https://your-app.onrender.com/api/dcf/TSM?wacc=0.10&tg=0.03
```

## Things to do after launch

1. **Custom domain.** Render lets you add `dcf.yourname.com` for free in the dashboard. CNAME from your DNS provider.
2. **Add analytics** if you want to know which tickers people search. Drop a Plausible or Umami snippet into the `<head>` in `main.py`. Avoid Google Analytics if you care about privacy and EU visitors.
3. **Cache to Redis** if you ever exceed one process. The current cache is per-process in-memory — fine for a single Render dyno, breaks if you scale to multiple workers.
4. **Move secrets to env vars** if you add anything sensitive (API keys, DB URLs). For now there are none — Yahoo is unauth.

## Known limitations of the model itself

Same as the local version. Worth keeping in mind before linking this anywhere:

- Flat 9% WACC default. A real model derives this per-name from beta, capital structure, cost of debt.
- Pure FCF extrapolation. No segment build, no margin modeling.
- Yahoo data has gaps for newer/smaller names — especially crypto miners (IREN, RIOT, CORZ) and pre-revenue companies.
- Terminal value usually drives ≥70% of EV. Sensitivity table makes that visible.

For pitch work, do your real model in Excel where every assumption is explicit. Use this for quick screens.
