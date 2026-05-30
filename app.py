"""
Health Agent — Streamlit UI for symptom triage and appointment booking.
Run with: streamlit run app.py
"""

import sys
from datetime import datetime
from pathlib import Path

# Ensure project root is on the path so imports work
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from agents.booking_agent import run_booking_workflow, triage_symptoms
from tools.hospital_tools import get_default_appointment_date

# Page configuration
st.set_page_config(
    page_title="Health Agent",
    page_icon="🏥",
    layout="centered",
)

# Session state defaults
if "history" not in st.session_state:
    st.session_state.history = []
if "last_result" not in st.session_state:
    st.session_state.last_result = None


def add_history(entry: str) -> None:
    """Append a line to the in-app conversation log."""
    st.session_state.history.append(entry)


# --- Header ---
st.title("Health Agent")
st.caption(
    "AI healthcare appointment & triage assistant (demo). "
    "**Not medical advice** — call emergency services for urgent emergencies."
)

# Show triage prompt reference (read-only context for learners)
prompt_path = PROJECT_ROOT / "prompts" / "triage_prompt.txt"
if prompt_path.exists():
    with st.expander("View triage assistant guidelines"):
        st.text(prompt_path.read_text(encoding="utf-8"))

st.divider()

# --- Symptom input ---
symptoms = st.text_area(
    "Describe your symptoms",
    placeholder="e.g. chest pain, fever, skin rash...",
    height=100,
)

# Quick triage preview (rule-based, no booking yet)
if symptoms.strip():
    preview = triage_symptoms(symptoms)
    risk = preview.get("risk_level", "Low")
    if risk == "High":
        st.error(f"Risk: **{risk}** — {preview.get('message', '')}")
    elif risk == "Medium":
        st.warning(f"Risk: **{risk}** — {preview.get('message', '')}")
    else:
        st.info(f"Risk: **{risk}** — {preview.get('message', '')}")

# --- Booking preferences ---
col1, col2 = st.columns(2)

with col1:
    specialty_choice = st.selectbox(
        "Specialty (optional — auto-detected from symptoms)",
        [
            "",
            "cardiologist",
            "general physician",
            "dermatologist",
        ],
        format_func=lambda x: "Auto-detect" if x == "" else x.replace("_", " ").title(),
    )

with col2:
    # Default to first date in slots.json (not "today") so the demo works out of the box
    default_date_str = get_default_appointment_date()
    if default_date_str:
        y, m, d = map(int, default_date_str.split("-"))
        default_date_value = datetime(y, m, d).date()
    else:
        default_date_value = datetime.today().date()

    preferred_date = st.date_input(
        "Preferred date",
        value=default_date_value,
        help="Sample data has slots on 2026-06-02, 2026-06-03, and 2026-06-04.",
    )
    preferred_date_str = preferred_date.strftime("%Y-%m-%d")

preferred_time = st.text_input(
    "Preferred time (optional, 24h format e.g. 09:00)",
    placeholder="09:00",
)

# --- Run agent ---
if st.button("Run Health Agent", type="primary"):
    specialty = specialty_choice if specialty_choice else None

    try:
        result = run_booking_workflow(
            symptoms=symptoms,
            preferred_specialty=specialty,
            preferred_date=preferred_date_str,
            preferred_time=preferred_time or None,
            slot_id=None,
            conversation_history=[],  # one clean summary per run (avoids duplicate log lines)
        )
        st.session_state.last_result = result
        add_history(f"{symptoms or '—'} → {result.get('status')} ({preferred_date_str})")
    except ValueError as err:
        st.error(f"Data error: {err}")
    except Exception as err:
        st.error(f"Something went wrong: {err}")

result = st.session_state.last_result

# --- Display workflow result ---
if result:
    st.subheader("Agent result")
    status = result.get("status")

    if status == "escalated":
        esc = result.get("escalation", {})
        st.error("Human escalation required")
        st.json(esc)
        st.markdown(
            f"**Reason:** {esc.get('reason')}\n\n"
            f"**Summary:** {esc.get('conversation_summary')}"
        )

    elif status == "need_specialty":
        st.warning(result.get("message", "Please choose a specialty."))

    elif status == "need_date":
        st.warning(result.get("message", "Please pick a date."))

    elif status == "alternate_dates":
        st.warning(result.get("message", ""))
        doctor = result.get("doctor", {})
        st.write(f"**Doctor:** {doctor.get('name')} ({doctor.get('hospital')})")
        st.write("**Dates with openings:**")
        for alt_date in result.get("suggested_dates", []):
            if st.button(f"Check slots on {alt_date}", key=f"alt_date_{alt_date}"):
                try:
                    alt_result = run_booking_workflow(
                        symptoms=symptoms,
                        preferred_specialty=specialty_choice or None,
                        preferred_date=alt_date,
                        preferred_time=preferred_time or None,
                        slot_id=None,
                        conversation_history=[],
                    )
                    st.session_state.last_result = alt_result
                    add_history(f"Retried date {alt_date} → {alt_result.get('status')}")
                    st.rerun()
                except Exception as err:
                    st.error(str(err))

    elif status == "choose_slot":
        st.success(result.get("message", ""))
        doctor = result.get("doctor", {})
        st.write(f"**Doctor:** {doctor.get('name')} ({doctor.get('hospital')})")

        slots = result.get("slots", [])
        if slots:
            st.write("**Available slots:**")
            for slot in slots:
                label = f"{slot.get('date')} at {slot.get('time')} — ID: {slot.get('slot_id')}"
                if st.button(f"Book {label}", key=f"book_{slot.get('slot_id')}"):
                    try:
                        book_result = run_booking_workflow(
                            symptoms=symptoms,
                            preferred_specialty=specialty_choice or None,
                            preferred_date=preferred_date_str,
                            preferred_time=preferred_time or None,
                            slot_id=slot.get("slot_id"),
                            conversation_history=[],
                        )
                        st.session_state.last_result = book_result
                        add_history(f"Booked → {book_result.get('status')}")
                        st.rerun()
                    except Exception as err:
                        st.error(str(err))

    elif status == "confirmed":
        st.success(result.get("message", "Booking confirmed!"))
        booking = result.get("booking", {})
        st.balloons()
        st.json({"doctor": result.get("doctor"), "slot": booking})

    elif status == "error":
        st.error(result.get("message", "Booking failed."))

    else:
        st.write(result)

# --- Sidebar: conversation log & sample dates ---
with st.sidebar:
    st.header("Conversation log")
    if st.session_state.history:
        for line in st.session_state.history[-15:]:
            st.text(line)
    else:
        st.caption("No messages yet.")

    if st.button("Clear session"):
        st.session_state.history = []
        st.session_state.last_result = None
        st.rerun()

    st.divider()
    st.subheader("Sample slot dates")
    st.caption("Try these dates from data/slots.json:")
    for d in ["2026-06-02", "2026-06-03", "2026-06-04"]:
        st.code(d)

    st.divider()
    st.subheader("Try these symptoms")
    st.markdown(
        "- `chest pain` → cardiologist (High risk)\n"
        "- `fever and cough` → general physician\n"
        "- `skin rash` → dermatologist\n"
        "- `difficulty breathing` → emergency escalation"
    )
