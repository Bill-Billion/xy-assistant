from __future__ import annotations

from app.services.intent_rules import extract_subject


def test_extract_subject_plain():
    assert extract_subject("我想学习广场舞") == "广场舞"


def test_extract_subject_double_learn():
    assert extract_subject("想学学八段锦") == "八段锦"


def test_extract_subject_course_suffix():
    assert extract_subject("学习二胡课程") == "二胡"


def test_extract_subject_question_suffix():
    assert extract_subject("想学习英语怎么说") == "英语"


def test_extract_subject_listen():
    assert extract_subject("我想听穆桂英挂帅") == "穆桂英挂帅"


def test_extract_subject_none():
    assert extract_subject("学东西吗") is None
