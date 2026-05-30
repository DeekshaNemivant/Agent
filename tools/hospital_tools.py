"""
Hospital tool functions — read/write JSON data for doctors and appointment slots.
These functions simulate "tools" an AI agent would call during booking.
"""

import json
from pathlib import Path
from typing import Any

# Paths to data files (relative to project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCTORS_FILE = PROJECT_ROOT / "data" / "doctors.json"
SLOTS_FILE = PROJECT_ROOT / "data" / "slots.json"


def _load_json(file_path: Path) -> list[dict[str, Any]]:
    """Load a JSON file and return a list of records. Handles missing or corrupt files."""
    try:
        if not file_path.exists():
            return []
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        return data
    except (json.JSONDecodeError, OSError) as err:
        raise ValueError(f"Could not read {file_path.name}: {err}") from err


def _save_json(file_path: Path, data: list[dict[str, Any]]) -> None:
    """Save a list of records back to a JSON file."""
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError as err:
        raise ValueError(f"Could not write {file_path.name}: {err}") from err


def find_doctor(specialty: str) -> dict[str, Any]:
    """
    Find the first available doctor for a given specialty.

    Args:
        specialty: e.g. 'cardiologist', 'general physician', 'dermatologist'

    Returns:
        Doctor record dict, or empty dict if none found.
    """
    if not specialty or not specialty.strip():
        return {"error": "Specialty is required."}

    specialty_normalized = specialty.strip().lower()
    doctors = _load_json(DOCTORS_FILE)

    for doctor in doctors:
        if doctor.get("specialty", "").lower() == specialty_normalized:
            return doctor

    return {}


def get_all_available_slots(doctor_id: str | None = None) -> list[dict[str, Any]]:
    """
    Return all unbooked slots, optionally filtered by doctor.

    Sorted by date then time — useful when the preferred date has no openings.
    """
    slots = _load_json(SLOTS_FILE)
    available: list[dict[str, Any]] = []

    for slot in slots:
        if slot.get("booked", False):
            continue
        if doctor_id and slot.get("doctor_id") != doctor_id:
            continue
        available.append(slot)

    return sorted(available, key=lambda s: (s.get("date", ""), s.get("time", "")))


def get_dates_with_available_slots(doctor_id: str | None = None) -> list[str]:
    """Return sorted unique dates (YYYY-MM-DD) that still have open slots."""
    slots = get_all_available_slots(doctor_id)
    dates = {s.get("date") for s in slots if s.get("date")}
    return sorted(dates)


def get_default_appointment_date() -> str:
    """First date with open slots — used as the UI default so demos don't pick 'today'."""
    dates = get_dates_with_available_slots()
    if dates:
        return dates[0]
    return ""


def get_available_slots(date: str, doctor_id: str | None = None) -> list[dict[str, Any]]:
    """
    Return unbooked appointment slots for a given date (YYYY-MM-DD).

    Args:
        date: Preferred date string
        doctor_id: Optional filter by doctor

    Returns:
        List of available slot records.
    """
    if not date or not date.strip():
        return []

    date_normalized = date.strip()
    slots = _load_json(SLOTS_FILE)
    available: list[dict[str, Any]] = []

    for slot in slots:
        if slot.get("date") != date_normalized:
            continue
        if slot.get("booked", False):
            continue
        if doctor_id and slot.get("doctor_id") != doctor_id:
            continue
        available.append(slot)

    return available


def book_slot(slot_id: str) -> dict[str, Any]:
    """
    Book an appointment slot by ID. Marks the slot as booked in slots.json.

    Args:
        slot_id: Unique slot identifier

    Returns:
        Updated slot record on success, or dict with 'error' key on failure.
    """
    if not slot_id or not slot_id.strip():
        return {"error": "Slot ID is required."}

    slots = _load_json(SLOTS_FILE)
    slot_id_normalized = slot_id.strip()

    for slot in slots:
        if slot.get("slot_id") != slot_id_normalized:
            continue
        if slot.get("booked", False):
            return {"error": f"Slot {slot_id_normalized} is already booked."}
        slot["booked"] = True
        _save_json(SLOTS_FILE, slots)
        return {"success": True, "slot": slot}

    return {"error": f"Slot {slot_id_normalized} not found."}


def escalate_case(reason: str, conversation_summary: str) -> dict[str, Any]:
    """
    Build a human-escalation payload when automated handling is not enough.

    Args:
        reason: Why escalation happened
        conversation_summary: Short recap of the patient interaction

    Returns:
        Escalation record for display or logging.
    """
    return {
        "escalated": True,
        "reason": reason or "No reason provided.",
        "conversation_summary": conversation_summary or "No summary available.",
        "action": "A human coordinator will review this case shortly.",
    }
