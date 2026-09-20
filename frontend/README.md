# Product Voice dashboard

React 19 and TypeScript dashboard for Product Voice. It provides Supabase email
authentication, workspace onboarding, product management, collection controls,
and analytics backed by FastAPI and Elasticsearch.

The Vite development server runs on port 3000 and proxies `/api` to FastAPI on
port 8000. Supabase's publishable configuration is loaded from
`GET /config/public`; no service credentials are bundled into the frontend.

Ask Vox uses `@elevenlabs/react` and the API's authenticated voice session
endpoint. The ElevenLabs API key stays on the backend. For a second local API
instance, set `API_PROXY_TARGET` before running Vite.

Use `..\scripts\dev.ps1` from this directory, or follow the root README.
