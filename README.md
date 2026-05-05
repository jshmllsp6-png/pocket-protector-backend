# Pocket Protector — Backend

FastAPI backend powering the Pocket Protector mobile app — a real-time scam and deception awareness tool that returns calm, confidence-based assessments of text and images.

## Architecture
- **Framework:** FastAPI on Uvicorn
- **LLM:** OpenAI GPT-4.1 via emergentintegrations (using EMERGENT_LLM_KEY)
- **Storage:** None — strict zero-storage privacy architecture (ephemeral processing only)

## Deploy to Render

This repo is a Render Blueprint. To deploy:

1. Sign in to Render
2. Click New then Blueprint
3. Connect this GitHub repo
4. Render auto-detects render.yaml and prepares the service
5. When prompted, set EMERGENT_LLM_KEY env var (this is sync false in the blueprint, so Render asks for it)
6. Click Apply, service builds and deploys
7. Once status shows Live, your backend is reachable at https://pocket-protector-backend.onrender.com

## Verify deploy

curl https://pocket-protector-backend.onrender.com/health

curl https://pocket-protector-backend.onrender.com/api/health

curl -X POST https://pocket-protector-backend.onrender.com/api/analyze -H "Content-Type: application/json" -d '{"text":"URGENT: confirm your password now"}'

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | / | Root health |
| GET | /health | K8s readiness probe |
| GET | /api/health | API readiness probe |
| GET | /api/ | API info |
| POST | /api/analyze | Main analysis endpoint (text or image_base64) |

## Environment variables (set in Render dashboard)

| Name | Required | Notes |
|---|---|---|
| EMERGENT_LLM_KEY | yes | Get from your Emergent account profile |
| MONGO_URL | no | Defaults to mongodb://localhost:27017 (unused — zero-storage) |
| DB_NAME | no | Defaults to pocket_protector (unused) |
