from __future__ import annotations

from .models import NotificationMessage, RingSchedule


def build_mock_notifications(schedule: list[RingSchedule]) -> list[NotificationMessage]:
    messages: list[NotificationMessage] = []
    for ring in schedule:
        if not ring.events:
            continue
        first_event = ring.events[0]
        messages.append(
            NotificationMessage(
                id=f"notif-{ring.ring_id}-warmup",
                channel="sms",
                text=(
                    f"{ring.ring_name}: Warm-up call for {first_event.division_name} at "
                    f"minute {first_event.start_minute}."
                ),
            )
        )
    messages.append(
        NotificationMessage(
            id="notif-admin-summary",
            channel="email",
            text="Schedule published for demo mode. Notification pipeline is currently mocked.",
        )
    )
    return messages
