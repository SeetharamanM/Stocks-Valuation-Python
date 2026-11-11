# Deploying on Streamlit Community Cloud

`app.py` is a Flask app, which Streamlit Cloud cannot run. `streamlit_app.py`
is a Streamlit front-end over the same pipeline: same inputs, same report. It
shows the report in the page and offers it as an `.html` download.

## 1. Try it locally

```bash
pip install -r requirements.txt
```

```bash
streamlit run streamlit_app.py
```

Opens `http://localhost:8501`. Upload `Aurionpro Sol.xlsx` with ticker
`AURIONPRO` to check that it works.

## 2. Push the code to GitHub

Streamlit Cloud deploys from a GitHub branch. Merge this branch into `main`, or
pick this branch when you deploy.

## 3. Create the app

1. Go to <https://share.streamlit.io> and sign in with GitHub. Allow access to
   private repositories if the repo is private.
2. Click **Create app**, then **Deploy a public app from GitHub**.
3. Fill in the fields:
   - **Repository:** `SeetharamanM/Stocks-Valuation-Python`
   - **Branch:** `main` (or the branch you pushed)
   - **Main file path:** `streamlit_app.py`
   - **App URL:** choose a subdomain
4. Under **Advanced settings**, set **Python version** to 3.12 or 3.13.
   **Secrets** can stay empty because the app uses no API keys. To change a
   default rate, add it in TOML form, for example `RISK_FREE_RATE = "0.068"`.
5. Click **Deploy**. The first build installs `requirements.txt` and takes a few
   minutes.

Each push to that branch redeploys the app automatically.

## 4. Decide who can see it

By default, anyone with the URL can use the app. To limit it to chosen people,
open the app's **Settings → Sharing** and invite their email addresses. If the
repository is private, the app is private by default.

## Personal-details checklist

Go through this before the repository or the app becomes public.

| Item | Status | Action |
|---|---|---|
| API keys, passwords, tokens | None in the code or the history. `.env` is gitignored. | None needed |
| `.env` file | Not committed | Keep it out of git |
| Git commit author email | Every commit carries the author's real email. Anyone who can see the repo can read it. | Use GitHub's `noreply` address for future commits (GitHub → Settings → Emails → "Keep my email address private"). Past commits keep the old address unless history is rewritten. |
| `deploy/README.md` | Names the GitHub account and repo. It contains no hostnames, IP addresses or Tailscale names. | Fine if the repo is public |
| `Aurionpro Sol.xlsx` | Office metadata names the author of the Screener.in template, not you | None needed |
| `aurionpro.pdf`, `aurionpro transcript.pdf` | Public company filings with no author metadata | None needed |
| Uploaded spreadsheets on Streamlit | Each run works in a temporary folder that is deleted afterwards, so visitors cannot see each other's files | None needed |
| Outbound data | The Yahoo Finance lookup sends only the ticker. Type in the market fields to skip it. | None needed |
