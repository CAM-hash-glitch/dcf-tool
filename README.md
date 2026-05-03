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

DCF Calculator
Type a ticker, get an estimated intrinsic value via discounted cash flow. Pulls financials from Yahoo Finance, projects free cash flow 5 years out, discounts back to present, and compares to the current share price.

![A screenshot of the tool would go here once you add one — see "Adding a screenshot" below.]


Why this runs locally and not on a public URL
Short version: Yahoo Finance actively blocks cloud servers (Render, AWS, Vercel, etc.) from scraping their data, but works fine from residential IPs. So the tool runs perfectly on your laptop and breaks when deployed. Rather than pay for a proxy service or rewrite against a paid API, this version is local-only.

If you want to deploy it publicly, see the "Deploying it yourself" section below — it's doable, but you'll need a real financial data API key.


Run it locally (5 minutes)
Prerequisites
You need Python 3.10 or newer. Check what you have:

python --version

If that returns "command not found" or "Python 2.x", install Python from python.org/downloads. On Windows, check the box "Add Python to PATH" during install — easy to miss, fixes a lot of headaches later.
Setup
Open a terminal in this folder. On Windows: open the folder in File Explorer, click in the address bar, type cmd, press Enter — your terminal opens already in the right place.

# 1. Create a virtual environment (isolates this project's dependencies)

python -m venv venv

# 2. Activate it

#    Windows (cmd):

venv\Scripts\activate

#    Windows (Git Bash) or Mac/Linux:

source venv/bin/activate

# 3. Install dependencies

pip install -r requirements.txt

You'll see (venv) at the start of your terminal prompt when the environment is active. That's how you know it worked.
Run
uvicorn main:app --reload

Open http://127.0.0.1:8000 in your browser.

To stop the server, press Ctrl + C in the terminal.
Every time after the first run
You only do the install once. After that:

venv\Scripts\activate         # or: source venv/bin/activate

uvicorn main:app --reload


What it does
For any ticker:

Pulls operating cash flow and capex from Yahoo (last reported year) → base FCF
Computes historical revenue CAGR from the income statement → growth rate (clamped between -10% and +25% to avoid blowups)
Projects FCF 5 years out, discounts at 9% WACC
Adds Gordon-growth terminal value (2.5% perpetual)
Subtracts net debt (debt − cash) → equity value
Divides by shares outstanding → intrinsic value per share
Compares to current price → margin of safety
Shows a 5×5 sensitivity table over WACC and terminal growth

Assumptions are adjustable in the UI (WACC, terminal growth, projection years).


Files
File
Purpose
main.py
FastAPI app: routes, rate limiting, validation, embedded HTML UI
dcf.py
Pure DCF engine + 1-hour cache
requirements.txt
Python dependencies
render.yaml
Render deploy config (only useful if you swap data sources)
Dockerfile
Container config (only useful if you swap data sources)



Limitations of the model
This is a quick-screen tool, not a substitute for a real model.

Flat 9% WACC for every name. A proper WACC depends on beta, cost of debt, and capital structure — varies meaningfully by company.
Pure FCF extrapolation. No segment build, no margin assumptions, no working capital modeling.
Yahoo data has gaps, especially for newer/smaller names and non-US listings.
Terminal value usually drives 70%+ of enterprise value. Small changes in WACC and terminal growth move intrinsic value by a lot — that's what the sensitivity table is for. Look at it before forming a view.

For real pitch work, build the model in Excel where every assumption is explicit and defensible.


Deploying it yourself
This repo includes render.yaml and a Dockerfile, so the infrastructure for a public deploy is ready. But — as noted above — Yahoo blocks cloud IPs, so deploying this as-is will result in every request failing.

To make it actually work on a public URL, you'd need to:

Sign up for a financial data API that doesn't block cloud servers (Financial Modeling Prep has a free tier with 250 requests/day)
Rewrite dcf.py to fetch from that API instead of yfinance
Add the API key as an environment variable in your hosting platform

Then deploy to Render, Fly, Railway, or anywhere else that runs containers.


Adding a screenshot
After you have it running, take a screenshot of the tool with a ticker like AAPL or TSM loaded. Save it as screenshot.png in this folder, then commit it to the repo. Update the image link near the top of this README from the placeholder to:

![DCF Calculator screenshot](screenshot.png)

A screenshot is the single most useful thing on a project README — it tells visitors in two seconds whether the tool is worth their time.


Tech stack
Python · FastAPI · yfinance · pandas · numpy · vanilla JS frontend

Built as a portfolio project for equity research workflows. PRs and issues welcome.

