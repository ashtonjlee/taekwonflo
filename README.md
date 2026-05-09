# taekwonflo

TaekwonFlo hackathon MVP scaffold with:

- `backend/`: FastAPI app with placeholder scheduling/rescheduling/notifications modules
- `frontend/`: React + Tailwind UI with placeholder tournament pages

## Run locally

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```
