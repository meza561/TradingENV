import json
import pytest
from guard import broker_opt as b


def cap(store):
    def runner(argv, prompt):
        store["argv"], store["prompt"] = argv, prompt
        return json.dumps({"order": {"id": "x"}, "positions": [], "quotes": [],
                           "orders": []})
    return runner


def test_open_uses_limit_not_market():
    s = {}
    b.open_position("111", "oid-1", 0.77, "r1", runner=cap(s))
    assert 'type="limit"' in s["prompt"]
    assert 'type="market"' not in s["prompt"]
    assert 'price="0.77"' in s["prompt"]


def test_open_is_buy_to_open():
    s = {}
    b.open_position("111", "oid-1", 0.77, "r1", runner=cap(s))
    assert '"side":"buy"' in s["prompt"] and '"position_effect":"open"' in s["prompt"]


def test_open_is_always_one_contract():
    s = {}
    b.open_position("111", "oid-1", 0.77, "r1", runner=cap(s))
    assert 'quantity="1"' in s["prompt"]


def test_close_is_sell_to_close():
    s = {}
    b.close_position("111", "oid-1", 2, 0.55, "r2", runner=cap(s))
    assert '"side":"sell"' in s["prompt"]
    assert '"position_effect":"close"' in s["prompt"]
    assert 'quantity="2"' in s["prompt"]


def test_each_call_allows_exactly_one_tool():
    for fn, args in ((b.open_position, ("1", "o", 0.5, "r")),
                     (b.positions, ("1",)),
                     (b.quotes, (["a"],))):
        s = {}
        fn(*args, runner=cap(s))
        assert s["argv"].count("--allowedTools") == 1
        assert len(s["argv"][-1].split(",")) == 1


def test_read_calls_never_carry_the_order_tool():
    for fn, args in ((b.positions, ("1",)), (b.quotes, (["a"],)),
                     (b.orders, ("1",))):
        s = {}
        fn(*args, runner=cap(s))
        assert b.PLACE_TOOL not in " ".join(s["argv"])


@pytest.mark.parametrize("bad", [0, -1, -0.01])
def test_refuses_nonpositive_limit(bad):
    with pytest.raises(ValueError, match="refusing"):
        b.open_position("1", "o", bad, "r", runner=cap({}))
    with pytest.raises(ValueError, match="refusing"):
        b.close_position("1", "o", 1, bad, "r", runner=cap({}))


def test_close_refuses_zero_quantity():
    with pytest.raises(ValueError, match="refusing"):
        b.close_position("1", "o", 0, 0.5, "r", runner=cap({}))


def test_empty_quote_request_makes_no_call():
    called = []
    b.quotes([], runner=lambda a, p: called.append(1) or "{}")
    assert called == []


def test_unparseable_output_raises():
    with pytest.raises(ValueError, match="no JSON"):
        b.positions("1", runner=lambda a, p: "sorry")


def test_portfolio_parses_nested_buying_power():
    def runner(argv, prompt):
        return json.dumps({"total_value": "149.94",
                           "buying_power": {"buying_power": "0.0000"}})
    assert b.portfolio("1", runner=runner) == (149.94, 0.0)


def test_portfolio_parses_flat_buying_power():
    def runner(argv, prompt):
        return json.dumps({"total_value": "300", "buying_power": "300"})
    assert b.portfolio("1", runner=runner) == (300.0, 300.0)


def test_portfolio_garbage_sizes_to_zero_not_a_guess():
    def runner(argv, prompt):
        return json.dumps({"total_value": "n/a", "buying_power": None})
    assert b.portfolio("1", runner=runner) == (0.0, 0.0)


def test_null_list_fields_return_empty_not_none():
    """A JSON null must not propagate as None into iteration."""
    def runner(argv, prompt):
        return json.dumps({"positions": None, "quotes": None, "orders": None})
    assert b.positions("1", runner=runner) == []
    assert b.quotes(["a"], runner=runner) == []
    assert b.orders("1", runner=runner) == []
