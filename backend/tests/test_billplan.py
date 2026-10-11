"""Bill split planner: hand-computed bills. Every expected number below was worked out by hand from the inputs."""
import pytest

from medibot.billplan import Item, Offer, Terms, plan, single_pharmacy_plans


def off(ph, price, qty, pid="p", asked=True, name=None):
    return Offer(ph, pid, name or pid, price, qty, True, asked)


# ---------------------------------------------------------------- packs
@pytest.mark.parametrize("units,qty,packs", [(15, 10, 2), (10, 10, 1), (30, 15, 2), (1, 10, 1), (16, 15, 2),
                                             (100, 60, 2), (60, 60, 1), (61, 60, 2)])
def test_whole_packs(units, qty, packs):
    assert off("a", 10, qty).packs_for(units) == packs


def test_overbuy_is_reported():
    p = plan([Item("1", "Dolo 650", 15, [off("netmeds", 25.18, 10)])], {})
    line = p.carts[0].lines[0]
    assert line.packs == 2 and line.cost == 50.36 and line.overbuy_units == 5


# ---------------------------------------------------------------- hand-computed bills
def test_one_item_cheapest_pack_wins_even_with_different_pack_sizes():
    # 30 tablets. A: strip of 15 at 24.53 -> 2 strips = 49.06. B: strip of 10 at 25.20 -> 3 strips = 75.60
    it = Item("1", "Dolo 650", 30, [off("pharmeasy", 24.53, 15), off("truemeds", 25.20, 10)])
    p = plan([it], {})
    assert p.pharmacies == ["pharmeasy"] and p.total == 49.06


def test_split_beats_one_pharmacy_without_fees():
    # X: A 100 / B 150 ; Y: A 200 / B 120 -> split A(X)+B(Y) = 220 ; all-A 300 ; all-B 270
    items = [Item("x", "X", 10, [off("a", 100, 10, "x"), off("b", 150, 10, "x")]),
             Item("y", "Y", 10, [off("a", 200, 10, "y"), off("b", 120, 10, "y")])]
    p = plan(items, {})
    assert p.total == 220 and sorted(p.pharmacies) == ["a", "b"]
    singles = single_pharmacy_plans(items, {})
    assert [s.total for s in singles] == [270, 300]


def test_delivery_fee_makes_one_pharmacy_cheaper():
    # same as above, fee 60 each, free above 500. split = 100+60 + 120+60 = 340 ; all-B = 270+60 = 330 -> all-B wins
    items = [Item("x", "X", 10, [off("a", 100, 10, "x"), off("b", 150, 10, "x")]),
             Item("y", "Y", 10, [off("a", 200, 10, "y"), off("b", 120, 10, "y")])]
    terms = {"a": Terms(60, 500), "b": Terms(60, 500)}
    p = plan(items, terms)
    assert p.pharmacies == ["b"] and p.total == 330 and p.carts[0].delivery_fee == 60


def test_free_delivery_threshold():
    # 3 strips of 180 = 540 >= 500 -> free ; else 540 + 0
    p = plan([Item("1", "A", 30, [off("a", 180, 10)])], {"a": Terms(50, 500)})
    assert p.total == 540 and p.carts[0].delivery_fee == 0
    p2 = plan([Item("1", "A", 20, [off("a", 180, 10)])], {"a": Terms(50, 500)})
    assert p2.total == 410 and p2.carts[0].delivery_fee == 50


def test_minimum_order_forces_a_different_plan():
    # a has min order 300: X alone at a (100) is not allowed -> buy both at b (150+120 = 270)
    items = [Item("x", "X", 10, [off("a", 100, 10, "x"), off("b", 150, 10, "x")]),
             Item("y", "Y", 10, [off("b", 120, 10, "y")])]
    p = plan(items, {"a": Terms(min_order=300)})
    assert p.pharmacies == ["b"] and p.total == 270


def test_identical_alternative_is_used_when_cheaper_and_tie_prefers_the_asked_product():
    it = Item("1", "Augmentin 625", 10, [off("netmeds", 166.08, 10, "aug"), off("1mg", 47.40, 10, "imclav", asked=False)])
    p = plan([it], {})
    assert p.total == 47.40 and not p.carts[0].lines[0].offer.is_asked_product
    tie = Item("1", "X", 10, [off("a", 50, 10, "alt", asked=False), off("a", 50, 10, "asked")])
    assert plan([tie], {}).carts[0].lines[0].offer.is_asked_product


def test_item_without_any_offer_is_reported_not_dropped_silently():
    p = plan([Item("1", "A", 10, [off("a", 10, 10)]), Item("2", "Unknown", 10, [])], {})
    assert p.unplaced == ["2"] and p.total == 10


def test_unknown_fee_is_flagged():
    p = plan([Item("1", "A", 10, [off("a", 10, 10)])], {"a": Terms()})
    assert p.carts[0].fee_known is False and p.carts[0].delivery_fee == 0


def test_tie_prefers_fewer_pharmacies():
    # split costs exactly the same as one pharmacy -> one pharmacy
    items = [Item("x", "X", 10, [off("a", 100, 10, "x"), off("b", 100, 10, "x")]),
             Item("y", "Y", 10, [off("a", 100, 10, "y"), off("b", 100, 10, "y")])]
    assert len(plan(items, {}).carts) == 1


def test_moving_an_item_to_a_dearer_pharmacy_can_be_cheaper_overall():
    """Why the planner is not greedy: X alone at its cheapest pharmacy misses b's minimum order / free delivery.
    X: a 90, b 100 ; Y: b 120 only. b: fee 50, free at >= 200 ; a: fee 50.
      greedy  : a(X) 90+50 + b(Y) 120+50                = 310
      optimum : b(X,Y) = 220 >= 200 -> free delivery     = 220"""
    items = [Item("x", "X", 10, [off("a", 90, 10, "x"), off("b", 100, 10, "x")]),
             Item("y", "Y", 10, [off("b", 120, 10, "y")])]
    p = plan(items, {"a": Terms(50), "b": Terms(50, 200)})
    assert p.total == 220 and p.pharmacies == ["b"]


def test_minimum_order_met_by_moving_items():
    """a: min order 200. X 90 + Y 100 at a = 190 < 200 is invalid; X 90 + Y 100 + Z 30 at a = 220 is fine."""
    items = [Item("x", "X", 10, [off("a", 90, 10, "x"), off("b", 120, 10, "x")]),
             Item("y", "Y", 10, [off("a", 100, 10, "y"), off("b", 130, 10, "y")]),
             Item("z", "Z", 10, [off("a", 30, 10, "z"), off("b", 20, 10, "z")])]
    p = plan(items, {"a": Terms(min_order=200)})
    assert p.total == 220 and p.pharmacies == ["a"]


def test_three_pharmacies_exact_optimum():
    # X: a 50 b 80 c 90 ; Y: a 90 b 40 c 95 ; Z: a 95 b 85 c 30 ; fee 25 each, free delivery at >= 100
    # all three   : a(X) 50+25, b(Y) 40+25, c(Z) 30+25                      = 195
    # b(X,Y)+c(Z) : b subtotal 120 >= 100 -> free = 120 ; c 30+25 = 55       = 175   <- optimum
    # a(X,Y)+c(Z) : a 140 free ; c 55                                        = 195
    # singles     : all-a 235, all-b 205, all-c 215 (each >= 100, free)      -> best single 205
    # (a first hand calculation forgot b's free delivery; the planner's exhaustive search caught it)
    items = [Item("x", "X", 10, [off("a", 50, 10, "x"), off("b", 80, 10, "x"), off("c", 90, 10, "x")]),
             Item("y", "Y", 10, [off("a", 90, 10, "y"), off("b", 40, 10, "y"), off("c", 95, 10, "y")]),
             Item("z", "Z", 10, [off("a", 95, 10, "z"), off("b", 85, 10, "z"), off("c", 30, 10, "z")])]
    terms = {k: Terms(25, 100) for k in "abc"}
    p = plan(items, terms)
    assert p.total == 175 and sorted(p.pharmacies) == ["b", "c"]
    assert plan(items, terms, max_pharmacies=1).total == 205
    assert [s.total for s in single_pharmacy_plans(items, terms)] == [205, 215, 235]


def test_planner_matches_brute_force_on_random_bills():
    """Exactness check: compare with trying EVERY assignment of every item to every pharmacy (fixed seed)."""
    import itertools
    import random
    rnd = random.Random(7)
    for _ in range(150):
        phs = ["a", "b", "c", "d"][: rnd.randint(1, 4)]
        terms = {ph: Terms(rnd.choice([None, 0, 25, 49]), rnd.choice([None, 199, 499]), rnd.choice([None, None, 150]))
                 for ph in phs}
        items = []
        for k in range(rnd.randint(1, 4)):
            offers = [off(ph, round(rnd.uniform(5, 300), 2), rnd.choice([10, 15, 30]), f"p{k}")
                      for ph in phs if rnd.random() < 0.8]
            items.append(Item(str(k), f"I{k}", rnd.choice([10, 15, 30, 45]), offers))
        best = None
        choices = [it.offers for it in items]
        if any(not c for c in choices):
            continue
        for combo in itertools.product(*choices):
            carts: dict[str, float] = {}
            for it, o in zip(items, combo):
                carts[o.pharmacy] = round(carts.get(o.pharmacy, 0) + o.cost_for(it.units), 2)
            if any(not terms[ph].meets_minimum(s) for ph, s in carts.items()):
                continue
            total = round(sum(s + terms[ph].fee_for(s) for ph, s in carts.items()), 2)
            best = total if best is None else min(best, total)
        p = plan(items, terms)
        assert (p.total if p and not p.unplaced else None) == best, (items, terms)


def test_ml_items_and_paise_rounding():
    # syrup 100 ml from 60 ml bottles at 45.02 -> 2 bottles = 90.04
    p = plan([Item("1", "Calpol syrup", 100, [off("1mg", 45.02, 60)])], {})
    assert p.total == 90.04 and p.carts[0].lines[0].overbuy_units == 20
