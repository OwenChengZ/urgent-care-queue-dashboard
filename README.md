# Urgent Care Queue Dashboard

CareFlow is a prototype urgent-care scheduling system for walk-in clinics and emergency department style workflows. It includes a patient-facing Flutter app, a staff-facing Flutter web dashboard, and a FastAPI backend connected to the E-hospital database API.

This prototype is for decision support only. It does not replace doctors, diagnosis, or treatment.

## Main Features

- Patient check-in with patient ID, name, age, gender, symptoms, and medical history
- Risk Analysis Agent using DeepSeek to assign CTAS urgency level, risk score, summary, and recommended action
- CTAS-style rule engine as a safety layer for high-risk clinical patterns
- Queue Prioritization Agent with Emergency, Normal, and Non-Urgent queues
- Patient app status view showing global queue position, patients ahead, and estimated wait
- Doctor web dashboard with priority queues, consultation actions, completed history, and feedback alerts
- Feedback Alert Agent using DeepSeek plus keyword safety fallback for condition updates
- Database-backed workflow using patient ID and record ID for future visit context

## Project Structure

```text
backend.py                  FastAPI backend and AI/database workflow
backend_requirements.txt    Python backend dependencies
api.md                      E-hospital database API notes
flutter_frontend/           Doctor/staff Flutter web dashboard
patient_app/                Patient-facing Flutter app
RUN_GUIDE.md                Chinese/English local run guide
```

Older Streamlit prototype files are kept for reference, but the current workflow mainly uses `backend.py`, `flutter_frontend/`, and `patient_app/`.

## Database Tables

The prototype uses the E-hospital database API and links data through `patient_id` and `record_id`.

- `patients_registration`: stores basic patient registration data such as patient ID, name, date of birth, gender, and contact info.
- `healthcare_records`: stores each check-in / visit record, including symptoms, CTAS level, risk score, queue name, status, summary, action, and timestamps.
- `patient_feedback`: stores patient feedback and condition updates linked to the visit record.
- `medical_history`: stores patient-reported medical history notes when provided.

When the same patient returns, the backend can retrieve previous records and feedback to provide context for the Risk Analysis Agent.

## Backend Workflow

1. Patient app submits check-in data to the FastAPI backend.
2. Backend checks or creates `patients_registration`.
3. Risk Analysis Agent analyzes current symptoms plus previous visit context.
4. Backend saves the visit to `healthcare_records`.
5. Queue Prioritization Agent assigns the patient to Emergency, Normal, or Non-Urgent queue.
6. Patient app polls the backend for global queue position and status.
7. Doctor web dashboard updates consultation status through backend actions.
8. Patient feedback and condition updates are saved to `patient_feedback`.
9. Feedback Alert Agent uses DeepSeek and a safety fallback to raise staff alerts when needed.

## AI Agent Design

The system is not only a single prompt-response call. It combines AI agents with rule-based safety checks.

- The Risk Analysis Agent uses DeepSeek to interpret symptoms and generate CTAS decision-support output.
- A CTAS-style rule engine provides safety constraints for obvious high-risk cases.
- The Feedback Alert Agent uses DeepSeek to interpret patient updates after check-in.
- A keyword safety fallback triggers alerts for red-flag language such as inability to speak, breathing difficulty, chest pain, fainting, or urgent help requests.

If the AI model and rule layer disagree in a high-risk situation, the system follows the safer alert path.

## Local Setup

Install backend dependencies:

```powershell
cd "D:\Urgent Care Queue Dashboard Project"
py -3 -m pip install -r backend_requirements.txt
```

Set the DeepSeek API key:

```powershell
$env:DEEPSEEK_API_KEY="your_deepseek_api_key"
```

Run the backend:

```powershell
py -3 -m uvicorn backend:app --host 0.0.0.0 --port 8001 --reload
```

Check backend health:

```text
http://127.0.0.1:8001/health
```

API documentation:

```text
http://127.0.0.1:8001/docs
```

## Run Doctor Web Dashboard

```powershell
cd "D:\Urgent Care Queue Dashboard Project\flutter_frontend"
$env:Path += ";D:\Download\flutter_windows_3.44.4-stable\flutter\bin"
flutter pub get
flutter run -d chrome
```

The doctor dashboard uses the backend at:

```text
http://127.0.0.1:8001
```

## Run Patient App in Chrome for Testing

```powershell
cd "D:\Urgent Care Queue Dashboard Project\patient_app"
$env:Path += ";D:\Download\flutter_windows_3.44.4-stable\flutter\bin"
flutter pub get
flutter run -d chrome --dart-define=PATIENT_API_BASE=http://127.0.0.1:8001
```

For Android emulator testing, the default backend URL is:

```text
http://10.0.2.2:8001
```

## Notes

- Keep API keys in environment variables. Do not commit real API keys.
- Local JSON files under `Feedback_Data/` are ignored by Git.
- This is a course prototype for workflow demonstration and current implementation testing.
