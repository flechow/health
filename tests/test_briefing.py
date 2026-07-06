import send_briefing as sb

def _week(start, **vals):
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    return [{"data": (d0+timedelta(days=i)).isoformat(), **vals} for i in range(7)]

def test_weekly_summary_returns_title_body_and_never_raises():
    rows = _week("2026-06-15", waga=99.0, bialko=190, sen=7.5, hrv=60, kroki=9000, min_intensywne=30)
    rows = _week("2026-06-08", waga=100.0, bialko=190, sen=7.5, hrv=58, kroki=9000, min_intensywne=30) + rows
    title, body = sb.weekly_summary(rows)
    assert "Podsumowanie" in title
    assert isinstance(body, str) and len(body) > 0

def test_weekly_summary_never_raises_on_empty():
    title, body = sb.weekly_summary([])
    assert isinstance(title, str) and isinstance(body, str)

def test_activity_sessions_counts_active_days():
    from datetime import date
    rows = _week("2026-06-15", min_intensywne=30)
    # 7 active days that week
    assert sb.activity_sessions(rows, date.fromisoformat("2026-06-15")) == 7
