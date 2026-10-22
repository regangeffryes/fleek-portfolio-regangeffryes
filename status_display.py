"""Display labels for editable account action statuses."""
STATUS_LABELS = {
    "Pending": "🔴 Pending",
    "In progress": "🟠 In progress",
    "Needs review": "🟡 Needs review",
    "Completed": "🟢 Completed",
}
STATUS_OPTIONS = list(STATUS_LABELS.values())

def show_status(status):
    return STATUS_LABELS.get(str(status), STATUS_LABELS["Pending"])

def parse_status(label):
    for raw, display in STATUS_LABELS.items():
        if label == display or label == raw:
            return raw
    raise ValueError(f"Unknown action status: {label}")
