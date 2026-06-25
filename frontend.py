"""
Streamlit frontend for the FastAPI urgent care backend.

Run backend first:
    py -3 -m uvicorn backend:app --host 0.0.0.0 --port 8001 --reload

Run this frontend:
    py -3 -m streamlit run frontend.py
"""

from __future__ import annotations

from typing import Any, Dict, List

import requests
import streamlit as st


DEFAULT_API_BASE = "http://127.0.0.1:8001"
QUEUE_ORDER = ["Emergency Queue", "Normal Queue", "Non-Urgent Queue"]
QUEUE_HINTS = {
    "Emergency Queue": "CTAS 1-2",
    "Normal Queue": "CTAS 3",
    "Non-Urgent Queue": "CTAS 4-5",
}


st.set_page_config(
    page_title="Urgent Care Queue Frontend",
    page_icon="🏥",
    layout="wide",
)


def api_base() -> str:
    return st.session_state.get("api_base", DEFAULT_API_BASE).rstrip("/")


def api_request(method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
    try:
        response = requests.request(method, f"{api_base()}{path}", timeout=60, **kwargs)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError as exc:
        raise RuntimeError("Cannot connect to backend. Please run uvicorn backend first.") from exc
    except requests.exceptions.HTTPError as exc:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        raise RuntimeError(str(detail)) from exc
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"Backend request failed: {exc}") from exc


def load_dashboard() -> tuple[Dict[str, Any], Dict[str, Any]]:
    queues = api_request("GET", "/queues")
    patients = api_request("GET", "/patients")
    return queues, patients


def urgency_badge(level: int, label: str) -> str:
    colors = {
        1: ("#fde2e2", "#8a1522"),
        2: ("#ffe8d5", "#92400e"),
        3: ("#fef3c7", "#854d0e"),
        4: ("#dcfce7", "#166534"),
        5: ("#e2e8f0", "#334155"),
    }
    bg, fg = colors.get(level, ("#eef2f7", "#344054"))
    return (
        f"<span style='background:{bg};color:{fg};padding:6px 10px;"
        f"border-radius:999px;font-weight:700;font-size:13px;'>{label}</span>"
    )


def status_badge(text: str) -> str:
    return (
        "<span style='background:#eef2f7;color:#344054;padding:6px 10px;"
        f"border-radius:999px;font-weight:700;font-size:13px;'>{text}</span>"
    )


def refresh() -> None:
    st.session_state.refresh_counter = st.session_state.get("refresh_counter", 0) + 1


def submit_patient_action(local_id: int, action: str) -> None:
    try:
        result = api_request("POST", f"/patient/{local_id}/{action}")
        st.success(result.get("message", "Action completed."))
        refresh()
    except RuntimeError as exc:
        st.error(str(exc))


def submit_feedback(patient: Dict[str, Any], rating: str, message: str) -> None:
    payload = {
        "patient_id": patient["patient_id"],
        "rating": rating,
        "message": message,
        "ctas_level": patient.get("ctas_level"),
        "risk_score": patient.get("risk_score"),
    }
    try:
        api_request("POST", "/feedback", json=payload)
        if rating == "Reasonable":
            st.success(
                "Thank you. We are glad the urgency level matched your expectation. "
                "We hope the patient feels better soon."
            )
        else:
            st.info(
                "Thank you for the feedback. This case will be kept for clinical review "
                "and future system improvement."
            )
    except RuntimeError as exc:
        st.error(str(exc))


def render_patient(patient: Dict[str, Any]) -> None:
    with st.container(border=True):
        left, right = st.columns([1.5, 1])
        with left:
            st.subheader(patient.get("name", "Unnamed Patient"))
            st.caption(
                f"Patient ID: {patient.get('patient_id')} | "
                f"Age: {patient.get('age')} | Local case #{patient.get('id')}"
            )
        with right:
            st.markdown(
                urgency_badge(patient.get("ctas_level", 5), patient.get("urgency_label", "CTAS"))
                + " "
                + status_badge(patient.get("status", "Unknown")),
                unsafe_allow_html=True,
            )
            st.caption(
                f"Risk Score: {patient.get('risk_score', 'N/A')}/10 | "
                f"Waiting: {patient.get('waiting_minutes', 0)} min"
            )

        st.write(patient.get("clinical_summary", "No summary available."))

        with st.expander("Reasoning and recommended action"):
            st.markdown(f"**Reasoning:** {patient.get('reasoning', 'No reasoning available.')}")
            st.markdown(
                f"**Recommended action:** {patient.get('recommended_action', 'No action provided.')}"
            )

        action_col1, action_col2, action_col3 = st.columns(3)
        with action_col1:
            if st.button("Notify Patient", key=f"notify-{patient['id']}"):
                submit_patient_action(patient["id"], "notify")
        with action_col2:
            if st.button("Start Consultation", key=f"start-{patient['id']}"):
                submit_patient_action(patient["id"], "start")
        with action_col3:
            if st.button("Mark as Completed", key=f"complete-{patient['id']}", type="primary"):
                submit_patient_action(patient["id"], "complete")

        st.divider()
        st.markdown("**Feedback Chatbot**")
        rating = st.selectbox(
            "Was the urgency level reasonable?",
            ["Reasonable", "Too high", "Too low", "Unsure"],
            key=f"rating-{patient['id']}",
        )
        feedback = st.text_area(
            "Comment",
            placeholder="Add a short comment for future review...",
            key=f"feedback-{patient['id']}",
        )
        if st.button("Submit Feedback", key=f"submit-feedback-{patient['id']}"):
            submit_feedback(patient, rating, feedback)


def render_completed(completed: List[Dict[str, Any]]) -> None:
    if not completed:
        st.caption("No completed patients yet.")
        return

    for patient in completed:
        with st.container(border=True):
            st.markdown(f"**{patient.get('name', 'Unnamed Patient')}**")
            st.caption(
                f"Patient ID: {patient.get('patient_id')} | "
                f"{patient.get('urgency_label')} | Completed: {patient.get('completed_at', 'N/A')}"
            )


st.markdown(
    """
    <style>
      .block-container { padding-top: 1.8rem; }
      div[data-testid="stMetricValue"] { font-size: 2rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


with st.sidebar:
    st.title("Patient Check-in")
    st.caption("Streamlit frontend calling the FastAPI backend.")
    st.text_input("Backend API", value=DEFAULT_API_BASE, key="api_base")

    with st.form("checkin-form"):
        patient_id = st.number_input("Patient ID", min_value=0, value=0)
        name = st.text_input("Patient Name", placeholder="Testing Name 1")
        age = st.number_input("Age", min_value=0, max_value=125, value=35)
        symptoms = st.text_area("Symptom Description", placeholder="Describe current symptoms...")
        medical_history = st.text_area(
            "Optional Medical History",
            placeholder="Known conditions, medications, allergies...",
        )
        submitted = st.form_submit_button("Risk Analysis and Join Queue", type="primary")

    if submitted:
        payload: Dict[str, Any] = {
            "name": name.strip(),
            "age": int(age),
            "symptoms": symptoms.strip(),
            "medical_history": medical_history.strip(),
        }
        if patient_id:
            payload["patient_id"] = int(patient_id)

        try:
            with st.spinner("Risk Analysis Agent is reviewing the case..."):
                result = api_request("POST", "/intake", json=payload)
            patient = result["patient"]
            st.success(
                f"Added to {patient['queue_name']} | {patient['urgency_label']} | "
                f"Risk Score {patient['risk_score']}/10"
            )
            refresh()
        except RuntimeError as exc:
            st.error(f"Check-in failed: {exc}")

    st.info(
        "Decision support only. This prototype does not replace doctors, diagnosis, or treatment.",
        icon="ℹ️",
    )


st.title("Urgent Care Queue Dashboard")
st.caption("DTI6302 AX00 Intelligent Health Informatics Group 9")

top_col1, top_col2 = st.columns([1, 0.2])
with top_col2:
    if st.button("Refresh"):
        refresh()

try:
    queue_data, patient_data = load_dashboard()
except RuntimeError as exc:
    st.error(str(exc))
    st.stop()

summary = queue_data.get("summary", {})
active_patients = patient_data.get("active", [])
completed_patients = patient_data.get("completed", [])

metric_cols = st.columns(4)
metric_cols[0].metric("Total Patients", summary.get("total_patients", 0))
metric_cols[1].metric("Waiting", summary.get("waiting", 0))
metric_cols[2].metric("In Consultation", summary.get("in_consultation", 0))
metric_cols[3].metric("Completed / Discharged", summary.get("completed", 0))

main_col, side_col = st.columns([2, 1])

with main_col:
    st.header("Priority Queues")
    queues = queue_data.get("queues", {})
    for queue_name in QUEUE_ORDER:
        patients = queues.get(queue_name, [])
        with st.expander(f"{queue_name} ({QUEUE_HINTS[queue_name]}) - {len(patients)} patient(s)", expanded=True):
            if not patients:
                st.caption("No patients in this queue.")
            for patient in patients:
                render_patient(patient)

    st.header("Completed / Discharged History")
    render_completed(completed_patients)

with side_col:
    st.header("Urgency Distribution")
    levels = [1, 2, 3, 4, 5]
    counts = {
        f"CTAS {level}": sum(
            1 for patient in [*active_patients, *completed_patients] if patient.get("ctas_level") == level
        )
        for level in levels
    }
    st.bar_chart(counts)

    st.header("Backend Status")
    try:
        health = api_request("GET", "/health")
        st.json(health)
    except RuntimeError as exc:
        st.warning(str(exc))
