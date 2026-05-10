from __future__ import annotations

from app.main import repair_demo, reschedule_demo


def _print_validation(label: str, validation) -> None:
    print(f"\n=== {label} ===")
    print(f"valid: {validation.valid}")
    if validation.errors:
        print("errors:")
        for message in validation.errors:
            print(f" - {message}")
    if validation.warnings:
        print("warnings:")
        for message in validation.warnings:
            print(f" - {message}")


def main() -> None:
    medical_pause = reschedule_demo(emergency_type="medical_delay")
    _print_validation("reschedule/demo medical_pause", medical_pause.validation)

    referee_shortage = reschedule_demo(emergency_type="referee_shortage")
    _print_validation("reschedule/demo referee_shortage", referee_shortage.validation)

    coach_delayed = repair_demo(emergency_type="coach_conflict")
    _print_validation("repair/demo coach_delayed", coach_delayed.validation)


if __name__ == "__main__":
    main()
