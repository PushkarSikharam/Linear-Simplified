# Pixel

AI voice-first adaptive product demo agent prototype.

Current phase:

```text
Demo-ready MVP: product UI, controlled actions, chat wiring, retrieval context,
session intelligence, interruption handling, and browser voice input shell.
```

Run the frontend:

```bash
npm install
npm run dev:web
```

On Windows PowerShell, use `npm.cmd` if script execution blocks `npm.ps1`:

```bash
npm.cmd install
npm.cmd run dev:web
```

Backend setup:

```bash
py -m venv .venv
.venv\Scripts\python -m pip install -r apps\api\requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --app-dir apps\api --reload --port 8001
```

The frontend expects the API at:

```bash
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8001
```

Root scripts:

```bash
npm.cmd run dev:api
npm.cmd run dev:web
npm.cmd run start:api
npm.cmd run lint:web
npm.cmd run test:api
npm.cmd run test:web
npm.cmd run test:e2e
npm.cmd run build:web
```

Demo path:

```text
1. show sprint planning
2. open ticket for maya
3. create a ticket for Maya about login bug
4. how do I assign Maya's ticket
5. set up github integration
6. open salesforce
```

The same path is available as suggested turns in the chat panel. Use Reset to start
a clean reviewer session.
