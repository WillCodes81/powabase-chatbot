# Frontend

React + TypeScript + Vite frontend for the Powabase RAG chatbot backend.

## Run locally

1. Backend (from the repo root):
   ```bash
   .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```
2. Frontend (from `frontend/`):
   ```bash
   npm install
   npm run dev
   ```
3. Open `http://localhost:5173`, sign up, and go.

`VITE_API_BASE_URL` (see `.env.development`) points the frontend at `http://127.0.0.1:8000`. Change it if the backend runs elsewhere.

## Build

```bash
npm run build
```
