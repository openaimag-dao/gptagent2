from app.telegram.broadcast import parse_chat_ids


def test_parse_chat_ids_none():
    assert parse_chat_ids(None) == []


def test_parse_chat_ids_empty_string():
    assert parse_chat_ids("") == []


def test_parse_chat_ids_single():
    assert parse_chat_ids("123456789") == [123456789]


def test_parse_chat_ids_multiple_with_negative_group_id():
    assert parse_chat_ids("123456789, -100987654321") == [123456789, -100987654321]
