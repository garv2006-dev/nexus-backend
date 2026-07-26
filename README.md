# Nexus Backend

This is the FastAPI + MongoDB backend for the Nexus AI Chat Application.

## Setup

1. Create an application at [dashboard.clerk.com](https://dashboard.clerk.com).
2. Go to **API Keys** and click **Show JWT public key** (or **Advanced**) to find the **JWKS URL** and **Issuer** → go in `.env` as `CLERK_JWKS_URL` and `CLERK_ISSUER`.

No Clerk *secret* key is needed on the backend — it verifies session tokens directly against Clerk's public JWKS.

```bash
python3.14 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # Windows (no cp): copy .env.example .env
# edit .env: add CLERK_JWKS_URL, CLERK_ISSUER, and OPENAI_API_KEY (or GEMINI_API_KEY + AI_PROVIDER=gemini)
# MONGODB_URI defaults to mongodb://localhost:27017 — change it if you're using Atlas

uvicorn main:app --reload --port 8000
```

The API runs at `http://localhost:8000` (docs at `/docs`). On startup it connects
to MongoDB and creates two indexes.
Open **MongoDB Compass**, connect to the same URI, and you'll see `users`,
`chat_sessions`, and `chat_messages` collections appear as you use the app.

### Switching AI providers

Set `AI_PROVIDER` in `.env` to `openai` or `gemini`, with the matching
API key and model name.

## API reference

All `/api/sessions*` and `/api/users*` routes require `Authorization: Bearer <Clerk session token>`.

| Method | Path                           | Description                                    |
|--------|---------------------------------|-------------------------------------------------|
| GET    | `/api/users/me`                 | Get profile + credit balance (auto-creates user) |
| POST   | `/api/users/sync`                | Push Clerk display info (called once after login) |
| PATCH  | `/api/users/me`                 | Update display name / bio                       |
| POST   | `/api/sessions`                 | Create a new chat session                        |
| GET    | `/api/sessions`                 | List the current user's sessions                 |
| GET    | `/api/sessions/{id}`            | Get a session with its full history              |
| PATCH  | `/api/sessions/{id}`            | Rename a session                                 |
| DELETE | `/api/sessions/{id}`            | Delete a session and its messages                |
| POST   | `/api/sessions/{id}/messages`   | Send a message, stream the AI reply (1 credit)   |

## Deployment (Render)

1. Push your code to a GitHub repository.
2. Go to [Render](https://render.com/) and create a new **Web Service**.
3. Connect your repository and select the `backend` directory as the Root Directory.
4. Set the Environment to `Python 3`.
5. Set the **Build Command** to: `pip install -r requirements.txt`
6. Set the **Start Command** to: `uvicorn main:app --host 0.0.0.0 --port 10000`
7. Add the following Environment Variables:
   - `CLERK_JWKS_URL`: Your Clerk JWKS URL.
   - `CLERK_ISSUER`: Your Clerk Issuer URL.
   - `MONGODB_URI`: Your MongoDB Atlas connection string.
   - `OPENAI_API_KEY` (or `GEMINI_API_KEY` & `AI_PROVIDER=gemini`): Your AI provider key.
   - `FRONTEND_URL`: The URL of your deployed frontend (e.g., `https://your-frontend-url.vercel.app`) to configure CORS.
8. Deploy!
