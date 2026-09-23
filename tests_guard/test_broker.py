import json
import pytest
from guard import broker
from guard.broker import PLACE_TOOL, READ_TOOL, place_order, get_orders


def test_place_argv_carries_exactly_one_tool():
    seen = {}

    def runner(argv, prompt):
        seen["argv"], seen["prompt"] = argv, prompt
        return json.dumps({"order": {"id": "x"}})

    place_order("111", "VTI", 25.0, "r1", runner=runner)
    assert seen["argv"].count("--allowedTools") == 1
    assert seen["argv"][-1] == PLACE_TOOL
    assert READ_TOOL not in seen["argv"]


def test_read_argv_never_carries_the_order_tool():
    seen = {}

    def runner(argv, prompt):
        seen["argv"] = argv
        return json.dumps({"orders": []})

    get_orders("111", runner=runner)
    assert PLACE_TOOL not in seen["argv"]
    assert seen["argv"][-1] == READ_TOOL


def test_place_prompt_pins_every_argument():
    seen = {}

    def runner(argv, prompt):
        seen["prompt"] = prompt
        return json.dumps({"order": {}})

    place_order("680370186", "VTI", 25.0, "abc-123", runner=runner)
    p = seen["prompt"]
    for frag in ('account_number="680370186"', 'symbol="VTI"', 'side="buy"',
                 'type="market"', 'dollar_amount="25.00"', 'ref_id="abc-123"',
                 'market_hours="regular_hours"'):
        assert frag in p, f"missing {frag}"


def test_place_rejects_unparseable_output():
    with pytest.raises(ValueError, match="no JSON"):
        place_order("1", "VTI", 25.0, "r", runner=lambda a, p: "sorry!")


def test_get_orders_parses_list():
    out = get_orders("1", runner=lambda a, p: json.dumps(
        {"orders": [{"id": "1"}, {"id": "2"}]}))
    assert len(out) == 2


def test_get_orders_missing_key_is_empty():
    assert get_orders("1", runner=lambda a, p: json.dumps({})) == []


def test_nonzero_exit_surfaces_stderr(monkeypatch):
    class R:
        returncode, stdout, stderr = 1, "", "boom: session limit"

    monkeypatch.setattr(broker.subprocess, "run", lambda *a, **k: R())
    with pytest.raises(RuntimeError, match="session limit"):
        place_order("1", "VTI", 25.0, "r")
