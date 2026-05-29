"""이메일 텍스트 파싱."""

from app.services.email_parse import parse_emails_from_text


def test_parse_newlines_and_commas():
    text = "a@x.com\nb@y.com, c@z.com"
    valid, invalid = parse_emails_from_text(text)
    assert valid == ["a@x.com", "b@y.com", "c@z.com"]
    assert invalid == []


def test_parse_at_separated():
    text = "teacher1@school.kr@teacher2@school.kr"
    valid, _ = parse_emails_from_text(text)
    assert valid == ["teacher1@school.kr", "teacher2@school.kr"]


def test_parse_dedupe():
    text = "a@x.com, a@x.com"
    valid, _ = parse_emails_from_text(text)
    assert valid == ["a@x.com"]
