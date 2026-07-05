import fitatu
import pytest

RAW = {  # shape confirmed by Task 1 spike
    "dietPlan": {
        "breakfast": {"items": [
            {"name": "Owsianka", "energy": 300, "protein": 10, "carbohydrate": 50, "fat": 6, "fiber": 8, "eaten": True}]},
        "second_breakfast": {"items": [
            {"name": "Winogrona", "energy": 50, "protein": 0.5, "carbohydrate": 12, "fat": 0.2, "fiber": 1, "eaten": False}]},
        "dinner": {"items": []},
    },
    "water": {"waterConsumption": 3500},
}

def test_sums_all_items_ignoring_eaten_flag():
    out = fitatu.normalize_nutrition(RAW)
    assert out["bialko"] == pytest.approx(10.5, abs=0.05)      # 10 + 0.5, eaten:false still counted
    assert out["kcal_spozyte"] == pytest.approx(350, abs=0.05)
    assert out["wegle"] == pytest.approx(62, abs=0.05)
    assert out["tluszcz"] == pytest.approx(6.2, abs=0.05)
    assert out["blonnik"] == pytest.approx(9, abs=0.05)

def test_stores_full_raw_verbatim():
    out = fitatu.normalize_nutrition(RAW)
    assert out["fitatu"] == RAW

def test_empty_day_returns_null_core():
    raw = {"dietPlan": {"breakfast": {"items": []}, "dinner": {"items": []}}}
    out = fitatu.normalize_nutrition(raw)
    assert out["bialko"] is None
    assert out["kcal_spozyte"] is None
    assert out["fitatu"] == raw

def test_none_returns_all_null():
    out = fitatu.normalize_nutrition(None)
    assert out == {"bialko": None, "kcal_spozyte": None, "wegle": None,
                   "tluszcz": None, "blonnik": None, "fitatu": None}
