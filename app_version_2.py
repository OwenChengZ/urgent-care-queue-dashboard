"""
app.py - Streamlit dashboard for a healthcare smart scheduling system.

Install & run:
    pip install streamlit plotly
    streamlit run app_version_2.py

Set your DeepSeek API key in the environment before running:
    set DEEPSEEK_API_KEY=your_key_here
"""

import html
import http.client
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

try:
    import streamlit as st
except ModuleNotFoundError:
    print("\nStreamlit is not installed in this Python environment.")
    print("Install it with:")
    print("  py -3 -m pip install streamlit plotly")
    print("\nThen run the app with:")
    print('  py -3 -m streamlit run "D:\\Urgent Care Queue Dashboard Project\\app_version_2.py"')
    raise SystemExit(1)

try:
    import plotly.graph_objects as go
except ModuleNotFoundError:
    go = None


DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DATA_DIR = Path(os.getenv("SMART_SCHEDULING_DATA_DIR", Path(__file__).with_name("Feedback_Data")))
FEEDBACK_FILE = DATA_DIR / "feedback_log.json"


CTAS_LEVELS: Dict[int, Dict[str, str]] = {
    1: {
        "label": "Level 1: Resuscitation / Critical",
        "short": "Resuscitation / Critical",
        "color": "#b91c1c",
    },
    2: {
        "label": "Level 2: Emergent",
        "short": "Emergent",
        "color": "#c2410c",
    },
    3: {
        "label": "Level 3: Urgent",
        "short": "Urgent",
        "color": "#a16207",
    },
    4: {
        "label": "Level 4: Less Urgent",
        "short": "Less Urgent",
        "color": "#15803d",
    },
    5: {
        "label": "Level 5: Non-Urgent",
        "short": "Non-Urgent",
        "color": "#475569",
    },
}

STATUS_WAITING = "Waiting"
STATUS_CONSULTATION = "In Consultation"
STATUS_COMPLETED = "Completed / Discharged"


def safe_class_name(value: str) -> str:
    """Convert labels such as 'Less Urgent' into CSS-safe class names."""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def ctas_label(level: int) -> str:
    return CTAS_LEVELS[level]["label"]


def ctas_short(level: int) -> str:
    return CTAS_LEVELS[level]["short"]


def ctas_color(level: int) -> str:
    return CTAS_LEVELS[level]["color"]


def fallback_risk_score_from_ctas(level: int) -> int:
    """Map CTAS urgency to a simple 1-10 risk score if the model omits one."""
    return {1: 10, 2: 8, 3: 6, 4: 3, 5: 1}.get(level, 1)


def load_feedback_from_file() -> List[dict]:
    """Load locally saved feedback. Patient names are not stored in this file."""
    if not FEEDBACK_FILE.exists():
        return []

    try:
        with FEEDBACK_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return []

    return data if isinstance(data, list) else []


def save_feedback_to_file(feedback_items: List[dict]) -> None:
    """Persist feedback locally as JSON for demo review after the session ends."""
    FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with FEEDBACK_FILE.open("w", encoding="utf-8") as file:
        json.dump(feedback_items, file, ensure_ascii=False, indent=2)


@dataclass
class Patient:
    id: int
    name: str
    age: int
    symptoms: str
    medical_history: str
    ctas_level: int
    risk_score: int
    clinical_summary: str
    reasoning: str
    recommended_action: str
    status: str = STATUS_WAITING
    checked_in_at: datetime = field(default_factory=datetime.now)
    consultation_started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    notified_at: Optional[datetime] = None

    @property
    def waiting_minutes(self) -> int:
        end_time = self.consultation_started_at or datetime.now()
        return max(0, int((end_time - self.checked_in_at).total_seconds() // 60))


# Risk Analysis Agent: sends check-in symptoms to the LLM, validates CTAS output,
# and returns decision-support fields for staff review.
def analyze_patient_risk(name: str, age: int, symptoms: str, medical_history: str) -> dict:
    if not DEEPSEEK_API_KEY:
        raise RuntimeError(
            "DEEPSEEK_API_KEY is missing. Set it as an environment variable before using AI triage."
        )

    prompt = f"""
You are a healthcare triage decision-support assistant for emergency departments and walk-in clinics.
Analyze patient-reported information and map it to a CTAS-based urgency level.

This is decision support only. Do not diagnose, prescribe treatment, or replace clinician judgment.

Use exactly one of these CTAS levels:
- Level 1: Resuscitation / Critical
- Level 2: Emergent
- Level 3: Urgent
- Level 4: Less Urgent
- Level 5: Non-Urgent

Also assign a patient health risk score from 1 to 10.
Base the score on reported red flags, age, medical history, symptom severity, stability concerns, and uncertainty.

Patient information:
- Name: {name}
- Age: {age}
- Symptoms: {symptoms}
- Optional medical history: {medical_history or "Not provided"}

Return valid JSON only, with this exact schema:
{{
  "ctas_level": 1,
  "urgency_label": "Level 1: Resuscitation / Critical",
  "risk_score": 10,
  "clinical_summary": "One concise clinical intake summary in neutral language.",
  "reasoning": "A professional CTAS and risk justification in 3-5 sentences. Reference reported acuity, red-flag features, stability concerns, uncertainty, and why this level is more appropriate than adjacent levels when relevant. Do not diagnose.",
  "recommended_action": "Practical next operational action for clinic or emergency department staff, including reassessment or escalation triggers when appropriate."
}}
"""

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    body = json.dumps(
        {
            "model": DEEPSEEK_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": "Return JSON only. Be concise, cautious, and clinically conservative.",
                },
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
        raise RuntimeError(f"DeepSeek API call failed: {exc}") from exc

    if response.status != 200:
        raise RuntimeError(f"DeepSeek API returned HTTP {response.status}: {raw}")

    try:
        api_data = json.loads(raw)
        text = api_data["choices"][0]["message"]["content"].strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        result = json.loads(text)
    except Exception as exc:
        raise RuntimeError("The AI response could not be parsed as valid JSON.") from exc

    try:
        level = int(result["ctas_level"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("The AI response did not include a valid CTAS level.") from exc

    if level not in CTAS_LEVELS:
        raise RuntimeError(f"The AI response returned unsupported CTAS level: {level}")

    try:
        risk_score = int(result.get("risk_score", fallback_risk_score_from_ctas(level)))
    except (TypeError, ValueError):
        risk_score = fallback_risk_score_from_ctas(level)
    risk_score = max(1, min(10, risk_score))

    expected_label = ctas_label(level)
    if result.get("urgency_label") != expected_label:
        result["urgency_label"] = expected_label

    return {
        "ctas_level": level,
        "urgency_label": expected_label,
        "risk_score": risk_score,
        "clinical_summary": str(result.get("clinical_summary", "")).strip(),
        "reasoning": str(result.get("reasoning", "")).strip(),
        "recommended_action": str(result.get("recommended_action", "")).strip(),
    }


def init_session_state() -> None:
    if "patients" not in st.session_state:
        st.session_state.patients = [
            Patient(
                id=1,
                name="Testing Name 1",
                age=72,
                symptoms="Severe chest pain radiating to left arm with sweating.",
                medical_history="Hypertension.",
                ctas_level=2,
                risk_score=9,
                clinical_summary="Older adult with chest pain features concerning for cardiac illness.",
                reasoning=(
                    "The patient is an older adult reporting severe chest pain with radiation and diaphoresis, "
                    "which are red-flag features for a potentially time-sensitive cardiopulmonary condition. "
                    "The available information does not confirm cardiac disease, but the symptom pattern carries "
                    "a meaningful risk of deterioration and should not remain in the routine waiting stream. "
                    "CTAS Level 2 is appropriate because rapid assessment is required, while Level 1 would usually "
                    "require immediately unstable airway, breathing, circulation, or unresponsiveness."
                ),
                recommended_action=(
                    "Move to a monitored assessment area, obtain vital signs promptly, and notify clinical staff "
                    "for urgent review. Escalate immediately if chest pain worsens, syncope occurs, oxygenation drops, "
                    "or the patient becomes hemodynamically unstable."
                ),
            ),
            Patient(
                id=2,
                name="Testing Name 2",
                age=67,
                symptoms="Difficulty breathing and oxygen saturation reported as dropping.",
                medical_history="COPD.",
                ctas_level=1,
                risk_score=10,
                clinical_summary="Respiratory distress with reported oxygen desaturation.",
                reasoning=(
                    "Reported respiratory distress with falling oxygen saturation suggests a possible immediate "
                    "airway or breathing threat, especially with a history of COPD. The case requires conservative "
                    "prioritization because hypoxemia can progress quickly and may need immediate intervention. "
                    "CTAS Level 1 is justified when the intake description indicates active or impending compromise "
                    "of breathing, even before a definitive diagnosis is available."
                ),
                recommended_action=(
                    "Place the patient in the resuscitation or highest-acuity assessment area for immediate clinical "
                    "review. Check oxygen saturation and vital signs without delay and escalate if work of breathing, "
                    "mental status, or circulation worsens."
                ),
            ),
            Patient(
                id=3,
                name="Testing Name 3",
                age=42,
                symptoms="Sudden severe abdominal pain with nausea.",
                medical_history="No major history reported.",
                ctas_level=3,
                risk_score=6,
                clinical_summary="Acute severe abdominal pain requiring timely assessment.",
                reasoning=(
                    "Sudden severe abdominal pain with nausea may represent a clinically significant acute abdominal "
                    "process and requires timely assessment. The intake text does not report shock, altered mental "
                    "status, uncontrolled bleeding, or other immediate instability, so Level 1 or 2 is not clearly "
                    "supported from the available information. CTAS Level 3 reflects the need for urgent evaluation "
                    "and reassessment while acknowledging that the exact cause is undetermined."
                ),
                recommended_action=(
                    "Obtain vital signs, pain score, and focused nursing reassessment, then prioritize clinician "
                    "assessment. Escalate if severe persistent pain, fever, hypotension, syncope, rigid abdomen, "
                    "or repeated vomiting is observed."
                ),
            ),
            Patient(
                id=4,
                name="Testing Name 4",
                age=58,
                symptoms="Mild cough and low-grade fever since yesterday.",
                medical_history="Not provided.",
                ctas_level=4,
                risk_score=2,
                clinical_summary="Mild respiratory symptoms without red flags in the report.",
                reasoning=(
                    "The reported cough and low-grade fever are mild and recent in onset, with no documented "
                    "shortness of breath, chest pain, confusion, dehydration, or immunocompromising history in the "
                    "intake note. CTAS Level 4 is reasonable because assessment may still be beneficial, but the "
                    "current description does not indicate immediate instability or a high-risk red-flag pattern. "
                    "The level should be revisited if new risk factors or abnormal vital signs are identified."
                ),
                recommended_action=(
                    "Keep in the waiting queue with routine monitoring and provide reassessment if symptoms worsen. "
                    "Escalate for dyspnea, persistent high fever, low oxygen saturation, chest pain, or concerning "
                    "vital signs."
                ),
            ),
        ]
        st.session_state.completed_patients = []
        st.session_state.feedback = load_feedback_from_file()
        st.session_state.next_patient_id = 5
        st.session_state.last_notification = ""


# Queue Prioritization Agent: CTAS level is the primary priority key.
# Within the same CTAS level, higher risk score is prioritized before check-in time.
def priority_queue() -> List[Patient]:
    active = [
        patient
        for patient in st.session_state.patients
        if patient.status in (STATUS_WAITING, STATUS_CONSULTATION)
    ]
    return sorted(
        active,
        key=lambda patient: (patient.ctas_level, -patient.risk_score, patient.checked_in_at),
    )


def summary_stats() -> dict:
    active = st.session_state.patients
    completed = st.session_state.completed_patients
    return {
        "total": len(active) + len(completed),
        "waiting": sum(1 for patient in active if patient.status == STATUS_WAITING),
        "consultation": sum(1 for patient in active if patient.status == STATUS_CONSULTATION),
        "completed": len(completed),
    }


def urgency_counts() -> Dict[int, int]:
    counts = {level: 0 for level in CTAS_LEVELS}
    for patient in st.session_state.patients + st.session_state.completed_patients:
        counts[patient.ctas_level] += 1
    return counts


def find_active_patient(patient_id: int) -> Optional[Patient]:
    for patient in st.session_state.patients:
        if patient.id == patient_id:
            return patient
    return None


# Dashboard actions: notify, start consultation, and complete/discharge update
# only in-memory session state; no patient data is saved permanently.
def notify_patient(patient: Patient) -> None:
    patient.notified_at = datetime.now()
    st.session_state.last_notification = (
        f"{patient.name} notified at {patient.notified_at.strftime('%H:%M:%S')}."
    )


def start_consultation(patient: Patient) -> None:
    patient.status = STATUS_CONSULTATION
    patient.consultation_started_at = datetime.now()


def mark_completed(patient: Patient) -> None:
    patient.status = STATUS_COMPLETED
    patient.completed_at = datetime.now()
    st.session_state.completed_patients.append(patient)
    st.session_state.patients = [
        active_patient
        for active_patient in st.session_state.patients
        if active_patient.id != patient.id
    ]


def add_patient_from_intake(name: str, age: int, symptoms: str, medical_history: str) -> Patient:
    analysis = analyze_patient_risk(name, age, symptoms, medical_history)
    new_patient = Patient(
        id=st.session_state.next_patient_id,
        name=name,
        age=age,
        symptoms=symptoms,
        medical_history=medical_history,
        ctas_level=analysis["ctas_level"],
        risk_score=analysis["risk_score"],
        clinical_summary=analysis["clinical_summary"],
        reasoning=analysis["reasoning"],
        recommended_action=analysis["recommended_action"],
    )
    st.session_state.patients.append(new_patient)
    st.session_state.next_patient_id += 1
    return new_patient


def render_badge(text: str, css_class: str) -> str:
    return f'<span class="badge {css_class}">{escape(text)}</span>'


def render_patient_card(patient: Patient, rank: Optional[int] = None) -> None:
    urgency_class = safe_class_name(ctas_label(patient.ctas_level))
    color = ctas_color(patient.ctas_level)
    rank_text = f"#{rank}" if rank is not None else "Completed"
    if patient.status == STATUS_CONSULTATION:
        status_class = "status-consultation"
    elif patient.status == STATUS_COMPLETED:
        status_class = "status-completed"
    else:
        status_class = "status-waiting"

    st.markdown(
        f"""
        <div class="queue-row urgency-{urgency_class}">
            <div class="row-top">
                <span class="rank" style="color:{color};">{escape(rank_text)}</span>
                <strong>{escape(patient.name)}</strong>
                <span class="muted">Age {patient.age}</span>
                {render_badge(ctas_label(patient.ctas_level), "urgency-badge " + urgency_class)}
                {render_badge(patient.status, status_class)}
                <span class="risk-score">Risk Score: {patient.risk_score}/10</span>
                <span class="wait-time">Wait: {patient.waiting_minutes} min</span>
            </div>
            <div class="summary">{escape(patient.clinical_summary)}</div>
            <div class="symptoms">{escape(patient.symptoms)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.expander("Review details", expanded=False):
        st.markdown(f"**Risk score:** {patient.risk_score}/10")
        st.markdown(f"**CTAS and risk justification:** {patient.reasoning}")
        st.markdown(f"**Suggested staff action:** {patient.recommended_action}")
        if patient.medical_history:
            st.markdown(f"**Medical history noted:** {patient.medical_history}")


def generate_feedback_bot_response(rating: str, feedback_message: str) -> str:
    """Generate a short patient-facing feedback response, with a safe local fallback."""
    if rating == "Reasonable":
        fallback = "Thank you for your feedback. We are glad to support your care and wish you a smooth recovery."
    else:
        fallback = (
            "Thank you for letting us know. Your feedback will be reviewed so we can improve the triage support system."
        )

    if not DEEPSEEK_API_KEY:
        return fallback

    prompt = f"""
Write a brief patient-facing response to feedback about an urgent care queue decision.

Rules:
- English only.
- 1-2 short sentences.
- Do not mention diagnosis or treatment.
- Do not include patient names.
- If rating is Reasonable, thank the patient and wish them a smooth recovery.
- If rating is Too high, Too low, or Unsure, acknowledge the concern and say it will be reviewed to improve the system.

Rating: {rating}
Feedback: {feedback_message}
"""
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    body = json.dumps(
        {
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": "Return only the short response text."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
    )

    try:
        conn = http.client.HTTPSConnection("api.deepseek.com", timeout=20)
        conn.request("POST", "/chat/completions", body=body, headers=headers)
        response = conn.getresponse()
        raw = response.read().decode("utf-8")
        conn.close()
        if response.status != 200:
            return fallback
        data = json.loads(raw)
        text = data["choices"][0]["message"]["content"].strip()
        return text[:300] if text else fallback
    except Exception:
        return fallback


def render_feedback_dialog_body(feedback_options: List[Patient]) -> None:
    st.caption("Share feedback about the urgency level. Patient names are not shown in this chatbot.")

    selected_patient_id = st.selectbox(
        "Select patient",
        options=[patient.id for patient in feedback_options],
        format_func=lambda patient_id: f"Patient #{patient_id}",
        key="feedback_dialog_patient",
    )
    selected_patient = next(patient for patient in feedback_options if patient.id == selected_patient_id)

    with st.form("patient_feedback_chat_form", clear_on_submit=True):
        feedback_rating = st.selectbox(
            "Rating",
            ["Reasonable", "Too high", "Too low", "Unsure"],
            key="feedback_dialog_rating",
        )
        feedback_message = st.text_area(
            "Feedback message",
            placeholder="Type patient feedback, follow-up concern, or staff note...",
            height=100,
            key="feedback_dialog_message",
        )
        submitted_feedback = st.form_submit_button("Send Feedback", use_container_width=True)

    if submitted_feedback:
        if not feedback_message.strip():
            st.error("Please enter a feedback message.")
        else:
            if feedback_rating == "Reasonable":
                assistant_response = "很高兴为您服务，祝您早日康复。"
            else:
                assistant_response = "收到反馈，这边会继续完善系统，并提交给临床团队复核。"

            assistant_response = generate_feedback_bot_response(feedback_rating, feedback_message.strip())

            feedback_item = {
                "patient_id": selected_patient.id,
                "patient_reference": f"Patient #{selected_patient.id}",
                "ctas_level": selected_patient.ctas_level,
                "urgency_label": ctas_label(selected_patient.ctas_level),
                "risk_score": selected_patient.risk_score,
                "rating": feedback_rating,
                "message": feedback_message.strip(),
                "assistant_response": assistant_response,
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
            st.session_state.feedback.append(feedback_item)
            try:
                save_feedback_to_file(st.session_state.feedback)
                with st.chat_message("user"):
                    st.markdown(f"**Patient #{selected_patient.id}**")
                    st.caption(f"Rating: {feedback_rating}")
                    st.write(feedback_message.strip())
                with st.chat_message("assistant"):
                    st.write(assistant_response)
            except OSError as exc:
                st.error(f"Feedback saved in this session, but local file save failed: {exc}")


st.set_page_config(
    page_title="Healthcare Smart Scheduling System",
    page_icon="healthcare",
    layout="wide",
    initial_sidebar_state="collapsed",
)

render_feedback_dialog = st.dialog("Patient Feedback Chatbot")(render_feedback_dialog_body)

init_session_state()

st.markdown(
    """
    <style>
        .stApp {
            background: #f6f7f8;
            color: #1f2933;
        }
        h1, h2, h3 {
            color: #1f2933;
        }
        .card {
            background: #ffffff;
            border: 1px solid #d9dee3;
            border-radius: 6px;
            padding: 14px 16px;
            margin-bottom: 12px;
            box-shadow: none;
        }
        .stat-number {
            font-size: 2rem;
            font-weight: 750;
            line-height: 1.1;
        }
        .stat-label {
            color: #5f6b76;
            font-size: 0.78rem;
            font-weight: 650;
            letter-spacing: 0.03em;
            text-transform: uppercase;
        }
        .queue-row {
            background: #ffffff;
            border: 1px solid #d9dee3;
            border-radius: 6px;
            padding: 12px 14px;
            margin: 0 0 8px 0;
            box-shadow: none;
        }
        .row-top {
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }
        .rank {
            font-size: 1.05rem;
            font-weight: 800;
        }
        .muted, .symptoms, .reasoning {
            color: #5f6b76;
            font-size: 0.84rem;
        }
        .summary {
            margin-top: 8px;
            color: #344054;
            font-size: 0.9rem;
            font-weight: 600;
        }
        .symptoms {
            margin-top: 6px;
            font-style: italic;
        }
        .reasoning {
            margin-top: 4px;
        }
        .risk-score {
            color: #344054;
            font-size: 0.84rem;
            font-weight: 700;
        }
        .wait-time {
            color: #344054;
            font-size: 0.84rem;
            font-weight: 700;
            margin-left: auto;
        }
        .badge {
            display: inline-block;
            border-radius: 4px;
            font-size: 0.74rem;
            font-weight: 700;
            padding: 4px 8px;
            line-height: 1.1;
        }
        .level-1-resuscitation-critical {
            background: #f7dddd;
            color: #8f1d1d;
        }
        .level-2-emergent {
            background: #f4e2d4;
            color: #8f3c0d;
        }
        .level-3-urgent {
            background: #efe7c9;
            color: #73530a;
        }
        .level-4-less-urgent {
            background: #dcebdd;
            color: #25633a;
        }
        .level-5-non-urgent {
            background: #e3e7eb;
            color: #46515c;
        }
        .urgency-level-1-resuscitation-critical {
            border-left: 4px solid #b91c1c;
        }
        .urgency-level-2-emergent {
            border-left: 4px solid #c2410c;
        }
        .urgency-level-3-urgent {
            border-left: 4px solid #a16207;
        }
        .urgency-level-4-less-urgent {
            border-left: 4px solid #15803d;
        }
        .urgency-level-5-non-urgent {
            border-left: 4px solid #475569;
        }
        .risk-badge {
            background: #eef2ff;
            color: #3730a3;
        }
        .status-waiting {
            background: #e8ecef;
            color: #46515c;
        }
        .status-consultation {
            background: #dce7f5;
            color: #24527a;
        }
        .status-completed {
            background: #dcebdd;
            color: #25633a;
        }
        .cover-shell {
            max-width: 980px;
            margin: 4vh auto 0 auto;
            padding: 42px 46px;
            background: #ffffff;
            border: 1px solid #d9dee3;
            border-radius: 8px;
        }
        .cover-kicker {
            color: #5f6b76;
            font-size: 0.82rem;
            font-weight: 700;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            margin-bottom: 10px;
        }
        .cover-title {
            color: #1f2933;
            font-size: 3rem;
            font-weight: 760;
            line-height: 1.04;
            margin: 0 0 14px 0;
        }
        .cover-copy {
            color: #46515c;
            font-size: 1.05rem;
            line-height: 1.6;
            max-width: 720px;
            margin-bottom: 26px;
        }
        .cover-meta {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 10px;
            margin-top: 28px;
        }
        .cover-meta-item {
            border: 1px solid #e1e5e9;
            border-radius: 6px;
            padding: 12px 14px;
            color: #46515c;
            font-size: 0.88rem;
            background: #fafafa;
        }
        .cover-meta-item strong {
            display: block;
            color: #1f2933;
            font-size: 0.78rem;
            text-transform: uppercase;
            letter-spacing: 0.03em;
            margin-bottom: 4px;
        }
        .cover-form-shell {
            max-width: 980px;
            margin: 18px auto 0 auto;
            padding: 24px 28px;
            background: #ffffff;
            border: 1px solid #d9dee3;
            border-radius: 8px;
        }
        footer, .stDeployButton {
            visibility: hidden;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

if "show_cover" not in st.session_state:
    st.session_state.show_cover = True

if st.session_state.show_cover:
    st.markdown(
        """
        <div class="cover-shell">
            <div class="cover-title">Urgent Care Queue Dashboard</div>
            <div class="cover-copy">
                A walk-in intake board for CTAS-based queue support, patient feedback,
                and temporary clinic operations. Complete patient check-in below,
                or skip directly to the live queue for monitoring.
            </div>
            <div class="cover-meta">
                <div class="cover-meta-item">
                    <strong>Queue Logic</strong>
                    CTAS first, risk score second, check-in time third
                </div>
                <div class="cover-meta-item">
                    <strong>Data Handling</strong>
                    Patient records stay temporary in the session
                </div>
                <div class="cover-meta-item">
                    <strong>Clinical Use</strong>
                    Decision support only; clinical review required
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="cover-form-shell">', unsafe_allow_html=True)
    st.subheader("Patient Check-In")
    with st.form("cover_check_in_form", clear_on_submit=True):
        patient_name = st.text_input("Patient name", placeholder="e.g. John Smith")
        form_col_1, form_col_2 = st.columns([1, 2])
        with form_col_1:
            patient_age = st.number_input("Age", min_value=0, max_value=125, step=1)
        with form_col_2:
            medical_history = st.text_input(
                "Optional medical history",
                placeholder="Relevant diagnoses, medications, allergies, pregnancy, etc.",
            )
        symptom_description = st.text_area(
            "Symptom description",
            placeholder="Describe the main complaint, severity, duration, and red flags.",
            height=110,
        )
        submit_col, skip_col = st.columns([2, 1])
        with submit_col:
            submitted = st.form_submit_button("Risk Analysis and Join Queue", type="primary", use_container_width=True)
        with skip_col:
            skipped = st.form_submit_button("Skip to Queue Board", use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

    if skipped:
        st.session_state.show_cover = False
        st.rerun()

    if submitted:
        if not patient_name.strip() or not symptom_description.strip():
            st.error("Please enter patient name and symptom description.")
        else:
            with st.spinner("Reviewing intake and assigning queue priority..."):
                try:
                    new_patient = add_patient_from_intake(
                        patient_name.strip(),
                        int(patient_age),
                        symptom_description.strip(),
                        medical_history.strip(),
                    )
                    st.session_state.last_checkin_message = (
                        f"{new_patient.name} added as {ctas_label(new_patient.ctas_level)}."
                    )
                    st.session_state.show_cover = False
                    st.rerun()
                except Exception as exc:
                    st.error(f"Check-in failed: {exc}")

    st.stop()

top_left, top_right = st.columns([5, 1])
with top_right:
    if st.button("Back to cover", use_container_width=True):
        st.session_state.show_cover = True
        st.rerun()

header_left, header_right = st.columns([4, 2])
with header_left:
    st.title("Healthcare Smart Scheduling System")
    st.caption("DTI6302 AX00 Intelligent Health Informatics")
with header_right:
    st.info(
        "Decision support only. This app does not diagnose, prescribe treatment, "
        "or replace professional clinical judgment."
    )

if not DEEPSEEK_API_KEY:
    st.warning("DEEPSEEK_API_KEY is not set. New AI risk analysis will be unavailable until it is configured.")

if st.session_state.get("last_checkin_message"):
    st.success(st.session_state.last_checkin_message)
    st.session_state.last_checkin_message = ""

stats = summary_stats()
stat_cols = st.columns(4)
for col, label, value, color in [
    (stat_cols[0], "Total Patients", stats["total"], "#0284c7"),
    (stat_cols[1], "Waiting", stats["waiting"], "#eab308"),
    (stat_cols[2], "In Consultation", stats["consultation"], "#2563eb"),
    (stat_cols[3], "Completed / Discharged", stats["completed"], "#16a34a"),
]:
    col.markdown(
        f"""
        <div class="card" style="border-top: 3px solid {color}; text-align:center;">
            <div class="stat-number" style="color:{color};">{value}</div>
            <div class="stat-label">{escape(label)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

left, right = st.columns([1, 1.7], gap="large")

with left:
    st.subheader("Urgency Distribution")
    counts = urgency_counts()
    chart_data = {ctas_label(level): counts[level] for level in CTAS_LEVELS}

    if go is None:
        st.info("Install plotly for the styled urgency chart. Showing a Streamlit chart for now.")
        st.bar_chart(chart_data)
    else:
        fig = go.Figure(
            data=[
                go.Bar(
                    x=list(chart_data.keys()),
                    y=list(chart_data.values()),
                    marker_color=[ctas_color(level) for level in CTAS_LEVELS],
                    hovertemplate="%{x}<br>Patients: %{y}<extra></extra>",
                )
            ]
        )
        fig.update_layout(
            height=290,
            margin=dict(t=20, b=80, l=30, r=20),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(tickangle=-25, showgrid=False),
            yaxis=dict(dtick=1, gridcolor="#e5e7eb"),
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    st.subheader("Patient Feedback")
    # Patient feedback chatbot: messages are stored in session_state and local JSON.
    feedback_options = st.session_state.patients + st.session_state.completed_patients
    if not feedback_options:
        st.info("No patients available for feedback yet.")
    else:
        if st.button("Open Patient Feedback Chatbot", use_container_width=True):
            render_feedback_dialog(feedback_options)
        if st.session_state.feedback:
            st.caption(
                f"{len(st.session_state.feedback)} feedback item(s) loaded/stored. "
                f"Local file: {FEEDBACK_FILE}"
            )

with right:
    active_queue = priority_queue()
    completed_patients = st.session_state.completed_patients
    queue_tab, history_tab = st.tabs(
        [
            f"Priority Queue ({len(active_queue)})",
            f"Completed / Discharged ({len(completed_patients)})",
        ]
    )

    with queue_tab:
        if st.session_state.last_notification:
            st.success(st.session_state.last_notification)

        if not active_queue:
            st.info("No active patients in the queue.")
        else:
            for rank, patient in enumerate(active_queue, start=1):
                render_patient_card(patient, rank=rank)
                action_cols = st.columns([1, 1, 1, 2])

                if action_cols[0].button("Notify Patient", key=f"notify_{patient.id}"):
                    notify_patient(patient)
                    st.rerun()

                start_disabled = patient.status == STATUS_CONSULTATION
                if action_cols[1].button(
                    "Start Consultation",
                    key=f"start_{patient.id}",
                    disabled=start_disabled,
                ):
                    start_consultation(patient)
                    st.rerun()

                if action_cols[2].button("Mark as Completed", key=f"complete_{patient.id}"):
                    mark_completed(patient)
                    st.rerun()

    with history_tab:
        if not completed_patients:
            st.info("No completed or discharged patients yet.")
        else:
            for patient in sorted(
                completed_patients,
                key=lambda item: item.completed_at or item.checked_in_at,
                reverse=True,
            ):
                render_patient_card(patient)
                completed_at = (
                    patient.completed_at.strftime("%Y-%m-%d %H:%M:%S")
                    if patient.completed_at
                    else "Not recorded"
                )
                st.caption(f"Completed / discharged at: {completed_at}")

st.divider()
st.caption(
    "Temporary demo data only: patient records are kept in st.session_state. "
    f"Staff feedback is also saved locally to {FEEDBACK_FILE.name} without patient names."
)
