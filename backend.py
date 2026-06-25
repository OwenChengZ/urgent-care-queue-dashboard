"""
FastAPI backend for the Urgent Care Queue Dashboard.

This file is backend-only. It exposes APIs for a Flutter/Web frontend:
- Risk Analysis Agent with DeepSeek
- Queue Prioritization Agent with three operational queues
- Patient feedback persistence through the database API described in api.md
- Patient history retrieval so repeat visits can use previous feedback

Run:
    py -3 -m pip install -r backend_requirements.txt
    $env:DEEPSEEK_API_KEY="your_deepseek_key"
    py -3 -m uvicorn backend:app --host 0.0.0.0 --port 8001 --reload
"""

import http.client
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DATABASE_API_URL = os.getenv("DATABASE_API_URL", "https://aetab8pjmb.us-east-1.awsapprunner.com")

DATA_DIR = Path(os.getenv("SMART_SCHEDULING_DATA_DIR", Path(__file__).with_name("Feedback_Data")))
PATIENT_FILE = DATA_DIR / "patients.json"
COMPLETED_FILE = DATA_DIR / "completed_patients.json"
LOCAL_FEEDBACK_FILE = DATA_DIR / "feedback_log.json"

STATUS_WAITING = "Waiting"
STATUS_CONSULTATION = "In Consultation"
STATUS_COMPLETED = "Completed / Discharged"

QUEUE_EMERGENCY = "Emergency Queue"
QUEUE_NORMAL = "Normal Queue"
QUEUE_NON_URGENT = "Non-Urgent Queue"

CTAS_LEVELS: Dict[int, Dict[str, str]] = {
    1: {"label": "Level 1: Resuscitation / Critical", "short": "Resuscitation / Critical", "color": "#b91c1c"},
    2: {"label": "Level 2: Emergent", "short": "Emergent", "color": "#c2410c"},
    3: {"label": "Level 3: Urgent", "short": "Urgent", "color": "#a16207"},
    4: {"label": "Level 4: Less Urgent", "short": "Less Urgent", "color": "#15803d"},
    5: {"label": "Level 5: Non-Urgent", "short": "Non-Urgent", "color": "#475569"},
}


def ctas_label(level: int) -> str:
    return CTAS_LEVELS[level]["label"]


def queue_name_for_ctas(level: int) -> str:
    """Queue Prioritization Agent action: assign one of three operational queues."""
    if level in (1, 2):
        return QUEUE_EMERGENCY
    if level == 3:
        return QUEUE_NORMAL
    return QUEUE_NON_URGENT


def fallback_risk_score_from_ctas(level: int) -> int:
    return {1: 10, 2: 8, 3: 6, 4: 3, 5: 1}.get(level, 1)


@dataclass
class Patient:
    id: int
    patient_id: int
    name: str
    age: int
    symptoms: str
    medical_history: str
    ctas_level: int
    risk_score: int
    queue_name: str
    clinical_summary: str
    reasoning: str
    recommended_action: str
    status: str = STATUS_WAITING
    checked_in_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    consultation_started_at: Optional[str] = None
    completed_at: Optional[str] = None
    notified_at: Optional[str] = None


class IntakeRequest(BaseModel):
    patient_id: Optional[int] = Field(
        None,
        description="Database patient id if known. If omitted, backend uses a local demo id.",
    )
    name: str = Field(..., min_length=1)
    age: int = Field(..., ge=0, le=125)
    symptoms: str = Field(..., min_length=1)
    medical_history: str = ""


class FeedbackRequest(BaseModel):
    patient_id: int
    rating: str = Field(..., description="Reasonable, Too high, Too low, or Unsure")
    message: str = ""
    ctas_level: Optional[int] = None
    risk_score: Optional[int] = None


app = FastAPI(title="Urgent Care Queue Dashboard Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def load_json_list(path: Path) -> List[dict]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def save_json_list(path: Path, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(rows, file, ensure_ascii=False, indent=2)


def patient_from_dict(row: dict) -> Patient:
    fields = Patient.__dataclass_fields__.keys()
    return Patient(**{key: row[key] for key in fields if key in row})


def load_patients() -> List[Patient]:
    return [patient_from_dict(row) for row in load_json_list(PATIENT_FILE)]


def save_patients(patients: List[Patient]) -> None:
    save_json_list(PATIENT_FILE, [asdict(patient) for patient in patients])


def load_completed_patients() -> List[Patient]:
    return [patient_from_dict(row) for row in load_json_list(COMPLETED_FILE)]


def save_completed_patients(patients: List[Patient]) -> None:
    save_json_list(COMPLETED_FILE, [asdict(patient) for patient in patients])


def next_local_id(patients: List[Patient], completed: List[Patient]) -> int:
    ids = [patient.id for patient in patients + completed]
    return max(ids, default=0) + 1


def parse_dt(value: Optional[str]) -> datetime:
    if not value:
        return datetime.now()
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.now()


def waiting_minutes(patient: Patient) -> int:
    start = parse_dt(patient.checked_in_at)
    end = parse_dt(patient.consultation_started_at) if patient.consultation_started_at else datetime.now()
    return max(0, int((end - start).total_seconds() // 60))


def serialize_patient(patient: Patient) -> dict:
    row = asdict(patient)
    row["urgency_label"] = ctas_label(patient.ctas_level)
    row["waiting_minutes"] = waiting_minutes(patient)
    return row


def database_url(path: str) -> str:
    return f"{DATABASE_API_URL.rstrip('/')}/{path.lstrip('/')}"


def fetch_patient_history(patient_id: int, limit: int = 5) -> List[dict]:
    """Read previous feedback records from the professor-provided database API."""
    sql_payload = {
        "sql": (
            "SELECT * FROM patient_feedback "
            "WHERE patient_id = :patient_id "
            "ORDER BY datetime DESC "
            "LIMIT :limit"
        ),
        "replacements": {"patient_id": patient_id, "limit": limit},
    }
    try:
        response = requests.post(database_url("/sql/select"), json=sql_payload, timeout=12)
        response.raise_for_status()
        data = response.json()
        rows = data.get("data", [])
        return rows if isinstance(rows, list) else []
    except Exception:
        # Fallback for deployments where /sql/select is unavailable.
        try:
            response = requests.get(database_url("/table/patient_feedback"), timeout=12)
            response.raise_for_status()
            data = response.json()
            rows = data.get("data", [])
            if not isinstance(rows, list):
                return []
            matches = [row for row in rows if str(row.get("patient_id")) == str(patient_id)]
            return sorted(matches, key=lambda row: str(row.get("datetime", "")), reverse=True)[:limit]
        except Exception:
            return []


def save_feedback_to_database(feedback: dict, local_feedback: Optional[dict] = None) -> dict:
    """Write patient feedback to the database API and also keep a local fallback copy."""
    local_rows = load_json_list(LOCAL_FEEDBACK_FILE)
    local_rows.append(local_feedback or feedback)
    save_json_list(LOCAL_FEEDBACK_FILE, local_rows)

    try:
        response = requests.post(database_url("/table/patient_feedback"), json=feedback, timeout=12)
        response.raise_for_status()
        return {"saved_to_database": True, "database_response": response.json()}
    except Exception as exc:
        return {"saved_to_database": False, "error": str(exc)}


def format_history_for_prompt(history_rows: List[dict]) -> str:
    if not history_rows:
        return "No previous feedback records found."

    lines = []
    for row in history_rows:
        date = row.get("datetime") or row.get("created_at") or "unknown date"
        feedback = row.get("feedback") or row.get("message") or row.get("comment") or ""
        rating = row.get("rating") or row.get("feedback_type") or ""
        severe = row.get("is_severe")
        detail = f"- {date}: {feedback}"
        if rating:
            detail += f" | feedback type/rating: {rating}"
        if severe is not None:
            detail += f" | severe: {severe}"
        lines.append(detail)
    return "\n".join(lines)


def call_deepseek_json(prompt: str, system_message: str) -> dict:
    if not DEEPSEEK_API_KEY:
        raise HTTPException(
            status_code=400,
            detail="DEEPSEEK_API_KEY is missing. Set it before using the Risk Analysis Agent.",
        )

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    body = json.dumps(
        {
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
        }
    )

    try:
        conn = http.client.HTTPSConnection("api.deepseek.com", timeout=30)
        conn.request("POST", "/chat/completions", body=body, headers=headers)
        response = conn.getresponse()
        raw = response.read().decode("utf-8")
        conn.close()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"DeepSeek API call failed: {exc}") from exc

    if response.status != 200:
        raise HTTPException(status_code=502, detail=f"DeepSeek API returned HTTP {response.status}: {raw}")

    try:
        data = json.loads(raw)
        text = data["choices"][0]["message"]["content"].strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(text)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="DeepSeek response could not be parsed as JSON.") from exc


def risk_analysis_agent(request: IntakeRequest, history_rows: List[dict]) -> dict:
    history_text = format_history_for_prompt(history_rows)
    prompt = f"""
You are the Risk Analysis Agent for an urgent care queue system.

Task:
Analyze the current patient intake together with previous database feedback.
Generate decision-support output only. Do not diagnose, prescribe treatment, or replace clinician judgment.

CTAS urgency levels:
- Level 1: Resuscitation / Critical
- Level 2: Emergent
- Level 3: Urgent
- Level 4: Less Urgent
- Level 5: Non-Urgent

Current intake:
- Patient ID: {request.patient_id or "local demo patient"}
- Name: {request.name}
- Age: {request.age}
- Symptoms: {request.symptoms}
- Optional medical history: {request.medical_history or "Not provided"}

Previous patient feedback/history from database:
{history_text}

Return valid JSON only:
{{
  "ctas_level": 1,
  "urgency_label": "Level 1: Resuscitation / Critical",
  "risk_score": 10,
  "clinical_summary": "Short neutral summary.",
  "reasoning": "3-5 sentences explaining CTAS level, risk score, prior history impact, red flags, and uncertainty.",
  "recommended_action": "Practical next staff action."
}}
"""
    result = call_deepseek_json(
        prompt,
        "Return JSON only. Be concise, cautious, and clinically conservative.",
    )

    try:
        level = int(result["ctas_level"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Risk Analysis Agent returned an invalid CTAS level.") from exc

    if level not in CTAS_LEVELS:
        raise HTTPException(status_code=502, detail=f"Unsupported CTAS level: {level}")

    try:
        score = int(result.get("risk_score", fallback_risk_score_from_ctas(level)))
    except (TypeError, ValueError):
        score = fallback_risk_score_from_ctas(level)
    score = max(1, min(10, score))

    return {
        "ctas_level": level,
        "urgency_label": ctas_label(level),
        "risk_score": score,
        "queue_name": queue_name_for_ctas(level),
        "clinical_summary": str(result.get("clinical_summary", "")).strip(),
        "reasoning": str(result.get("reasoning", "")).strip(),
        "recommended_action": str(result.get("recommended_action", "")).strip(),
        "history_used": history_rows,
    }


def queue_prioritization_agent(patients: List[Patient]) -> dict:
    """Agent action: split active patients into three queues and sort each queue."""
    queues = {
        QUEUE_EMERGENCY: [],
        QUEUE_NORMAL: [],
        QUEUE_NON_URGENT: [],
    }
    for patient in patients:
        if patient.status not in (STATUS_WAITING, STATUS_CONSULTATION):
            continue
        queues.setdefault(patient.queue_name, []).append(patient)

    for name, rows in queues.items():
        rows.sort(key=lambda patient: (patient.ctas_level, -patient.risk_score, parse_dt(patient.checked_in_at)))
        queues[name] = [serialize_patient(patient) for patient in rows]

    return queues


def summary_payload(patients: List[Patient], completed: List[Patient]) -> dict:
    ctas_counts = {str(level): 0 for level in CTAS_LEVELS}
    for patient in patients + completed:
        ctas_counts[str(patient.ctas_level)] += 1
    return {
        "total": len(patients) + len(completed),
        "waiting": sum(1 for patient in patients if patient.status == STATUS_WAITING),
        "in_consultation": sum(1 for patient in patients if patient.status == STATUS_CONSULTATION),
        "completed": len(completed),
        "ctas_counts": ctas_counts,
    }


def get_patient_or_404(patient_id: int, patients: List[Patient]) -> Patient:
    for patient in patients:
        if patient.id == patient_id:
            return patient
    raise HTTPException(status_code=404, detail="Patient not found.")


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "deepseek_configured": bool(DEEPSEEK_API_KEY),
        "database_api_url": DATABASE_API_URL,
    }


@app.get("/ctas-levels")
def get_ctas_levels() -> dict:
    return CTAS_LEVELS


@app.get("/patient/{patient_id}/history")
def get_patient_history(patient_id: int) -> dict:
    return {"patient_id": patient_id, "history": fetch_patient_history(patient_id)}


@app.post("/intake")
def intake(request: IntakeRequest) -> dict:
    patients = load_patients()
    completed = load_completed_patients()
    local_id = next_local_id(patients, completed)
    database_patient_id = request.patient_id or local_id

    request_with_id = request.copy(update={"patient_id": database_patient_id})
    history_rows = fetch_patient_history(database_patient_id)
    analysis = risk_analysis_agent(request_with_id, history_rows)

    patient = Patient(
        id=local_id,
        patient_id=database_patient_id,
        name=request.name.strip(),
        age=request.age,
        symptoms=request.symptoms.strip(),
        medical_history=request.medical_history.strip(),
        ctas_level=analysis["ctas_level"],
        risk_score=analysis["risk_score"],
        queue_name=analysis["queue_name"],
        clinical_summary=analysis["clinical_summary"],
        reasoning=analysis["reasoning"],
        recommended_action=analysis["recommended_action"],
    )
    patients.append(patient)
    save_patients(patients)

    return {
        "message": "Risk Analysis Agent completed. Queue Prioritization Agent assigned the patient.",
        "patient": serialize_patient(patient),
        "analysis": analysis,
        "queues": queue_prioritization_agent(patients),
        "summary": summary_payload(patients, completed),
    }


@app.get("/queues")
def get_queues() -> dict:
    patients = load_patients()
    completed = load_completed_patients()
    return {
        "summary": summary_payload(patients, completed),
        "queues": queue_prioritization_agent(patients),
    }


@app.get("/patients")
def get_patients() -> dict:
    patients = load_patients()
    completed = load_completed_patients()
    return {
        "active": [serialize_patient(patient) for patient in patients],
        "completed": [serialize_patient(patient) for patient in completed],
    }


@app.get("/feedback")
def get_local_feedback() -> dict:
    return {"feedback": load_json_list(LOCAL_FEEDBACK_FILE)}


@app.post("/patient/{local_patient_id}/notify")
def notify_patient(local_patient_id: int) -> dict:
    patients = load_patients()
    patient = get_patient_or_404(local_patient_id, patients)
    patient.notified_at = datetime.now().isoformat(timespec="seconds")
    save_patients(patients)
    return {"message": "Patient notified.", "patient": serialize_patient(patient)}


@app.post("/patient/{local_patient_id}/start")
def start_consultation(local_patient_id: int) -> dict:
    patients = load_patients()
    patient = get_patient_or_404(local_patient_id, patients)
    patient.status = STATUS_CONSULTATION
    patient.consultation_started_at = datetime.now().isoformat(timespec="seconds")
    save_patients(patients)
    return {"message": "Consultation started.", "patient": serialize_patient(patient)}


@app.post("/patient/{local_patient_id}/complete")
def complete_patient(local_patient_id: int) -> dict:
    patients = load_patients()
    completed = load_completed_patients()
    patient = get_patient_or_404(local_patient_id, patients)
    patient.status = STATUS_COMPLETED
    patient.completed_at = datetime.now().isoformat(timespec="seconds")
    patients = [row for row in patients if row.id != local_patient_id]
    completed.append(patient)
    save_patients(patients)
    save_completed_patients(completed)
    return {
        "message": "Patient marked as completed/discharged.",
        "patient": serialize_patient(patient),
        "summary": summary_payload(patients, completed),
    }


@app.post("/feedback")
def save_feedback(request: FeedbackRequest) -> dict:
    feedback_text = request.message.strip()
    metadata_text = (
        f"Rating: {request.rating}; "
        f"CTAS Level: {request.ctas_level if request.ctas_level is not None else 'not provided'}; "
        f"Risk Score: {request.risk_score if request.risk_score is not None else 'not provided'}."
    )
    database_feedback = {
        "patient_id": request.patient_id,
        "treatment": "Urgent Care Queue Review",
        "feedback": f"{metadata_text} Feedback: {feedback_text}",
        "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "is_severe": "false",
        "feedback_type": "triage_review",
    }
    local_feedback = {
        **database_feedback,
        "rating": request.rating,
        "ctas_level": request.ctas_level,
        "risk_score": request.risk_score,
    }
    database_result = save_feedback_to_database(database_feedback, local_feedback)
    return {
        "message": "Feedback saved. It will be used as history for future risk analysis.",
        "feedback": local_feedback,
        "database": database_result,
    }
