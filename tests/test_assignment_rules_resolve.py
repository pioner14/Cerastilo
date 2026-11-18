"""core.assignment_rules: поправки правил по типу пункта."""

from types import SimpleNamespace

from core.assignment_rules import resolve_assignment_config

TALK = SimpleNamespace(id=4, required_qualification="ministry_speech", is_brothers_only=True)


def _resolve(atype, text="", marker=None, pos="4", base=TALK):
    return resolve_assignment_config("ministry", atype, text, marker, pos, base, lambda s, p: TALK)


def test_student_on_talk_position_is_open_with_assistant():
    c = _resolve("student", "Подготавливайте учеников")
    assert (c.kind, c.is_brothers_only, c.needs_assistant, c.required_qualification) == (
        "student",
        False,
        True,
        "ministry_item",
    )


def test_discussion_is_one_brother():
    c = _resolve("student", "Обсуждение", marker="(5 мин.) Обсуждение")
    assert (c.kind, c.is_brothers_only, c.needs_assistant) == ("discussion", True, False)


def test_what_would_you_say_is_elder_ms_only():
    c = _resolve("student", "Что бы вы сказали?")
    assert c.kind == "what_would_you_say" and c.is_elder_ms_only


def test_teaching_is_talk():
    c = _resolve("teaching", "Подготавливайте учеников", pos="1", base=None)
    assert (c.kind, c.is_brothers_only, c.required_qualification) == (
        "talk",
        True,
        "ministry_speech",
    )


def test_other_sections_unchanged():
    base = object()
    assert (
        resolve_assignment_config("treasures", "talk", "", None, "1", base, lambda s, p: None)
        is base
    )


def test_allowed_service_types_follow_s38():
    from core.assignment_rules import ELDER_MS_TYPES, ELDER_TYPES, allowed_service_types

    cfg = SimpleNamespace(required_qualification=None, assignment_name="")
    assert allowed_service_types("fixed", "chairman", cfg, "") == ELDER_TYPES
    assert allowed_service_types("living", "1", cfg, "Местные потребности") == ELDER_TYPES
    assert allowed_service_types("treasures", "2", cfg, "Духовные жемчужины") == ELDER_MS_TYPES
    assert allowed_service_types("living", "1", cfg, "Будьте щедрыми") == ELDER_MS_TYPES
    assert (
        allowed_service_types(
            "ministry", "3", _resolve("student", "Обсуждение", marker="(5 мин.) Обсуждение"), ""
        )
        == ELDER_MS_TYPES
    )
    assert (
        allowed_service_types("ministry", "1", _resolve("student", "Начинайте разговор"), "")
        is None
    )
    assert allowed_service_types("treasures", "3", cfg, "Чтение Библии") is None
