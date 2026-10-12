import pytest

from app.session_records import MESSAGE_LINE_BYTES, RecordError, iter_records


def lines(tmp_path, content: bytes):
    path = tmp_path / "s.jsonl"
    path.write_bytes(content)
    return path


def test_yields_line_numbers_and_records_with_none_for_bad_lines(tmp_path):
    path = lines(tmp_path, b'{"a":1}\n{broken\n[1]\n{"b":2}\n\xff\xfe\n{"c":NaN}\n')

    assert list(iter_records(path)) == [(1, {"a": 1}), (2, None), (3, None), (4, {"b": 2}), (5, None), (6, None)]


def test_an_over_long_line_is_skipped_whole_and_numbering_continues(tmp_path):
    path = lines(tmp_path, b'{"a":1}\n' + b"x" * (MESSAGE_LINE_BYTES + 5000) + b'\n{"b":2}\n')

    assert list(iter_records(path)) == [(1, {"a": 1}), (2, None), (3, {"b": 2})]


def test_deep_nesting_is_a_bad_line_not_a_crash(tmp_path):
    path = lines(tmp_path, b'{"a":' + b"[" * 100000 + b"]" * 100000 + b'}\n{"b":2}\n')

    assert list(iter_records(path)) == [(1, None), (2, {"b": 2})]


def test_strict_raises_naming_the_line_but_tolerates_a_torn_last_line(tmp_path):
    with pytest.raises(RecordError) as error:
        list(iter_records(lines(tmp_path, b'{"a":1}\n{broken\n{"b":2}\n'), strict=True))
    assert error.value.line == 2 and "JSON" in error.value.reason

    assert list(iter_records(lines(tmp_path, b'{"a":1}\n{"b'), strict=True)) == [(1, {"a": 1}), (2, None)]


def test_a_utf16_file_is_not_decoded_as_utf16(tmp_path):
    path = lines(tmp_path, '{"a":1}\n'.encode("utf-16"))

    assert all(record is None for _, record in iter_records(path))
