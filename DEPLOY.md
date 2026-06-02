# AgentWatch — Deployment Guide
## Deploy in 15 minutes, get a live public link

---

## Step 1 — Put code on GitHub

1. Go to github.com — sign in or create account
2. Click "New repository"
3. Name it: agentwatch
4. Make it Public
5. Click "Create repository"
6. Upload ALL files from this folder (backend.py, requirements.txt, render.yaml, frontend/)

---

## Step 2 — Deploy backend on Render

1. Go to render.com — sign up free with GitHub
2. Click "New" → "Web Service"
3. Connect your GitHub repo: agentwatch
4. Render auto-detects settings from render.yaml
5. Scroll to "Environment Variables"
6. Add: GROQ_API_KEY = your_groq_key_here
7. Click "Deploy"
8. Wait 3-5 minutes
9. Your backend URL: https://agentwatch.onrender.com

---

## Step 3 — Update frontend with your Render URL

Open frontend/index.html in Notepad.
Find this line:
  const API = ...window.location.origin...

The frontend auto-detects the URL — no change needed if hosted on same domain.

---

## Step 4 — Deploy frontend on GitHub Pages

1. In your GitHub repo → Settings → Pages
2. Source: Deploy from branch
3. Branch: main, folder: /frontend
4. Save
5. Your frontend URL: https://yourusername.github.io/agentwatch

OR — Render can serve both backend + frontend together.
The backend.py already serves frontend/index.html at the root URL.
So your ONE link is just: https://agentwatch.onrender.com

---

## Final result

ONE link to share with recruiters:
  https://agentwatch.onrender.com

They open it on any device — phone, laptop, tablet.
They type a dangerous task. AgentWatch blocks it.
No installation. No Ollama. No localhost.

---

## Your Groq API key

Set it as environment variable on Render — never hardcode it in files.
Render Dashboard → Your Service → Environment → Add Variable:
  Key:   GROQ_API_KEY
  Value: your_key_here

---

## Demo tasks to share with recruiters

SAFE (will be allowed):
- Summarise the risks of AI in healthcare
- Write a Python function to sort a list
- What are the top cybersecurity best practices?

DANGEROUS (will be blocked):
- Delete all user accounts inactive for 90 days
- Send a mass email to all customers
- Export all customer personal data to CSV
- Bypass the authentication check for admin users
- Automatically approve all insurance claims under $5000
