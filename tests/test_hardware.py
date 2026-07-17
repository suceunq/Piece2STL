from piece2stl.hardware import _parse_temperature_text, _valid_temperature


def test_amd_temperature_outputs_are_parsed():
    assert _parse_temperature_text('{"temperature_edge": 47.5}') == 47.5
    assert _parse_temperature_text('Temp (Edge) 63.0°C') == 63.0


def test_invalid_or_missing_temperatures_are_rejected():
    assert _valid_temperature(0) is None
    assert _valid_temperature(511) is None
    assert _parse_temperature_text("N/A") is None
