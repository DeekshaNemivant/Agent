"""
Booking agent — orchestrates symptom triage and appointment booking workflow.
Uses rule-based logic (no external LLM required) for portfolio simplicity.
"""

from typing import Any

from tools.hospital_tools import (
    book_slot,
    escalate_case,
    find_doctor,
    get_available_slots,
    get_dates_with_available_slots,
)

# Rule-based symptom → specialty mapping (keywords in lowercase)
SPECIALTY_RULES: list[tuple[list[str], str]] = [
    (["chest pain", "heart", "palpitation", "cardiac", "chest tightness"], "cardiologist"),
    (["fever", "cough", "cold", "flu", "sore throat", "fatigue", "headache"], "general physician"),
    (["rash", "skin", "acne", "itching", "eczema", "hives", "dermatitis"], "dermatologist"),
]

# Symptoms that always require emergency escalation
EMERGENCY_KEYWORDS: list[str] = [
    "difficulty breathing",
    "can't breathe",
    "cannot breathe",
    "severe bleeding",
    "unconscious",
    "loss of consciousness",
    "stroke",
    "face drooping",
    "chest pain and shortness of breath",
    "heart attack",
]

# Risk levels per matched specialty group
RISK_BY_SPECIALTY: dict[str, str] = {
    "cardiologist": "High",
    "general physician": "Medium",
    "dermatologist": "Low",
}


def triage_symptoms(symptom_text: str) -> dict[str, Any]:
    """
    Analyze symptom text and return specialty, risk level, and flags.

    Returns:
        dict with keys: specialty, risk_level, is_emergency, uncertain, message
    """
    text = (symptom_text or "").strip().lower()
    if not text:
        return {
            "specialty": None,
            "risk_level": "Low",
            "is_emergency": False,
            "uncertain": True,
            "message": "Please describe your symptoms.",
        }

    # Check emergencies first
    for keyword in EMERGENCY_KEYWORDS:
        if keyword in text:
            return {
                "specialty": "cardiologist",
                "risk_level": "High",
                "is_emergency": True,
                "uncertain": False,
                "message": "Emergency symptoms detected. Immediate escalation required.",
            }

    # Match specialty by keywords
    matched_specialty: str | None = None
    for keywords, specialty in SPECIALTY_RULES:
        if any(kw in text for kw in keywords):
            matched_specialty = specialty
            break

    if not matched_specialty:
        return {
            "specialty": None,
            "risk_level": "Medium",
            "is_emergency": False,
            "uncertain": True,
            "message": "Could not determine specialty from symptoms. Human review recommended.",
        }

    risk = RISK_BY_SPECIALTY.get(matched_specialty, "Medium")
    # Chest pain without full emergency phrase still high risk
    if "chest pain" in text:
        risk = "High"

    return {
        "specialty": matched_specialty,
        "risk_level": risk,
        "is_emergency": False,
        "uncertain": False,
        "message": f"Recommended specialty: {matched_specialty.replace('_', ' ')} (Risk: {risk})",
    }


def build_conversation_summary(history: list[str]) -> str:
    """Join chat history into a short summary for escalation."""
    if not history:
        return "No conversation history."
    return " | ".join(history[-8:])


def run_booking_workflow(
    symptoms: str,
    preferred_specialty: str | None,
    preferred_date: str,
    preferred_time: str | None,
    slot_id: str | None,
    conversation_history: list[str],
) -> dict[str, Any]:
    """
    Full agent workflow: triage → find doctor → slots → book or escalate.

    Returns a result dict the Streamlit UI can display.
    """
    history = list(conversation_history)
    history.append(f"Symptoms: {symptoms}")

    # Step 1: Triage
    triage = triage_symptoms(symptoms)
    specialty = (preferred_specialty or triage.get("specialty") or "").strip()

    if triage.get("is_emergency"):
        summary = build_conversation_summary(history)
        escalation = escalate_case(
            reason="Emergency symptoms detected",
            conversation_summary=summary,
        )
        return {"status": "escalated", "triage": triage, "escalation": escalation}

    if triage.get("uncertain") and not preferred_specialty:
        summary = build_conversation_summary(history)
        escalation = escalate_case(
            reason="Uncertain routing — could not map symptoms to a specialty",
            conversation_summary=summary,
        )
        return {"status": "escalated", "triage": triage, "escalation": escalation}

    if not specialty:
        return {
            "status": "need_specialty",
            "triage": triage,
            "message": "Please select or confirm a medical specialty to continue.",
        }

    history.append(f"Specialty: {specialty}")

    # Step 2: Find doctor
    doctor = find_doctor(specialty)
    if not doctor or doctor.get("error"):
        summary = build_conversation_summary(history)
        escalation = escalate_case(
            reason=f"No doctor available for specialty: {specialty}",
            conversation_summary=summary,
        )
        return {"status": "escalated", "triage": triage, "escalation": escalation}

    history.append(f"Doctor: {doctor.get('name')}")

    # Step 3: Date required
    if not preferred_date or not preferred_date.strip():
        return {
            "status": "need_date",
            "triage": triage,
            "doctor": doctor,
            "message": "Please choose a preferred appointment date.",
        }

    date_str = preferred_date.strip()
    history.append(f"Date: {date_str}")

    # Step 4: Get slots for the chosen date
    slots = get_available_slots(date_str, doctor_id=doctor.get("id"))
    if not slots:
        # Other dates may still have openings — suggest those before escalating
        suggested_dates = get_dates_with_available_slots(doctor.get("id"))
        if suggested_dates:
            return {
                "status": "alternate_dates",
                "triage": triage,
                "doctor": doctor,
                "requested_date": date_str,
                "suggested_dates": suggested_dates,
                "message": (
                    f"No openings on {date_str} for {doctor.get('name')}. "
                    f"Choose another date below (demo data: {', '.join(suggested_dates)})."
                ),
            }

        # No slots anywhere for this doctor — escalate to a human
        summary = build_conversation_summary(history)
        escalation = escalate_case(
            reason=f"No appointment slots available for {doctor.get('name')}",
            conversation_summary=summary,
        )
        return {
            "status": "escalated",
            "triage": triage,
            "doctor": doctor,
            "escalation": escalation,
        }

    # Optional time filter
    if preferred_time and preferred_time.strip():
        time_norm = preferred_time.strip()
        filtered = [s for s in slots if s.get("time") == time_norm]
        if filtered:
            slots = filtered

    # Step 5: Book if slot_id provided
    if slot_id and slot_id.strip():
        book_result = book_slot(slot_id.strip())
        if book_result.get("error"):
            return {
                "status": "error",
                "triage": triage,
                "doctor": doctor,
                "slots": slots,
                "message": book_result["error"],
            }
        booked = book_result.get("slot", {})
        history.append(f"Booked slot: {booked.get('slot_id')}")
        return {
            "status": "confirmed",
            "triage": triage,
            "doctor": doctor,
            "booking": booked,
            "message": (
                f"Appointment confirmed with {doctor.get('name')} "
                f"on {booked.get('date')} at {booked.get('time')}."
            ),
        }

    # Waiting for user to pick a slot
    return {
        "status": "choose_slot",
        "triage": triage,
        "doctor": doctor,
        "slots": slots,
        "message": "Select an available time slot below to complete booking.",
    }
