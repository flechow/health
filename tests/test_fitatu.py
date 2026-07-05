import fitatu
import pytest
import json
import base64
from unittest.mock import Mock, patch

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
    assert out["wegle"] is None
    assert out["tluszcz"] is None
    assert out["blonnik"] is None
    assert out["fitatu"] == raw

def test_none_returns_all_null():
    out = fitatu.normalize_nutrition(None)
    assert out == {"bialko": None, "kcal_spozyte": None, "wegle": None,
                   "tluszcz": None, "blonnik": None, "fitatu": None}

def test_login_raises_valueerror_when_token_missing():
    """Raises ValueError when login response has no token."""
    mock_response = Mock()
    mock_response.json.return_value = {}  # No 'token' key
    mock_response.raise_for_status.return_value = None

    with patch('fitatu.requests.Session.post', return_value=mock_response):
        with pytest.raises(ValueError, match="brak tokenu w odpowiedzi"):
            fitatu.login("test@example.com", "password")

def test_login_raises_valueerror_when_id_missing_in_jwt():
    """Raises ValueError when JWT payload has no id claim."""
    # Build a JWT token with no 'id' claim
    payload = {"sub": "user"}
    encoded_payload = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    fake_token = f"x.{encoded_payload}.y"

    mock_response = Mock()
    mock_response.json.return_value = {"token": fake_token}
    mock_response.raise_for_status.return_value = None

    with patch('fitatu.requests.Session.post', return_value=mock_response):
        with pytest.raises(ValueError, match="brak id uzytkownika w tokenie"):
            fitatu.login("test@example.com", "password")
