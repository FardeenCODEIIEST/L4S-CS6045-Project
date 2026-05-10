import pytest

from controller.runtime_api import parse_register_value


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("RuntimeCmd: reg_l4s_threshold[0]= 30\n", 30),
        ("reg_l4s_threshold[0]=30\n", 30),
        ("Obtaining JSON from switch...\nreg[0] 42\n", 42),
    ],
)
def test_parse_register_value(output, expected):
    assert parse_register_value(output) == expected


def test_parse_register_value_rejects_missing_value():
    with pytest.raises(ValueError):
        parse_register_value("RuntimeCmd: register_read failed\n")
