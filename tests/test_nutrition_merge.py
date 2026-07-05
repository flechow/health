import update_garmin as ug

def _row(d, **kw):
    r = {"data": d}
    r.update(kw)
    return r

def test_carry_forward_copies_nutrition_for_matching_date():
    old = [_row("2026-06-01", bialko=150, kcal_spozyte=2000, wegle=None,
                tluszcz=None, blonnik=None, fitatu={"x": 1})]
    new = [_row("2026-06-01"), _row("2026-06-02")]
    ug.carry_forward_nutrition(old, new)
    assert new[0]["bialko"] == 150
    assert new[0]["kcal_spozyte"] == 2000
    assert "bialko" not in new[1]  # no old data for that date

def test_carry_forward_does_not_overwrite_existing():
    old = [_row("2026-06-01", bialko=150)]
    new = [_row("2026-06-01", bialko=999)]
    ug.carry_forward_nutrition(old, new)
    assert new[0]["bialko"] == 999

def test_enrich_sets_recent_days_from_fetch():
    rows = [_row("2026-06-01"), _row("2026-06-02"), _row("2026-06-03")]
    def fake_fetch(day):
        return {"bialko": 100, "kcal_spozyte": 1800, "wegle": 150,
                "tluszcz": 60, "blonnik": 20, "fitatu": {"day": day}}
    ug.enrich_nutrition(rows, fake_fetch, days=2)
    assert "bialko" not in rows[0]           # outside the 2-day window
    assert rows[1]["bialko"] == 100
    assert rows[2]["kcal_spozyte"] == 1800

def test_enrich_skips_all_null_days():
    rows = [_row("2026-06-03")]
    def fake_fetch(day):
        return {"bialko": None, "kcal_spozyte": None, "wegle": None,
                "tluszcz": None, "blonnik": None, "fitatu": None}
    ug.enrich_nutrition(rows, fake_fetch, days=1)
    assert "bialko" not in rows[0]

def test_carry_forward_handles_none_old_rows():
    new = [_row("2026-06-01")]
    ug.carry_forward_nutrition(None, new)
    assert "bialko" not in new[0]

def test_enrich_overwrites_carried_forward_value():
    row = _row("2026-06-01", bialko=999)
    def fake_fetch(day):
        return {"bialko": 100, "kcal_spozyte": 1800, "wegle": 150,
                "tluszcz": 60, "blonnik": 20, "fitatu": {}}
    ug.enrich_nutrition([row], fake_fetch, days=1)
    assert row["bialko"] == 100
