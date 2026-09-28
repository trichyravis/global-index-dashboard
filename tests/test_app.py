from pathlib import Path
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_default_dashboard_and_controls():
    app = AppTest.from_file(APP, default_timeout=40).run()
    assert not app.exception
    assert app.metric[1].value == "257 / 496"
    assert len(app.get("plotly_chart")) == 8
    app.selectbox(key="rolling_kind").select("Sharpe").run()
    assert not app.exception
    app.selectbox(key="monthly_index").select("Nasdaq Composite").run()
    assert not app.exception
    app.checkbox(key="negative_only").check().run()
    assert not app.exception


def test_single_index_and_invalid_date_range():
    app = AppTest.from_file(APP, default_timeout=40).run()
    app.multiselect(key="indices").set_value(["Nifty 50"]).run()
    assert not app.exception
    assert app.metric[0].label == "Nifty 50 · price return"
    app.date_input(key="start_Bundled snapshot").set_value(app.date_input(key="end_Bundled snapshot").value).run()
    assert not app.exception
    assert any("end date after" in e.value for e in app.error)


def test_upload_mode_waits_for_data():
    app = AppTest.from_file(APP, default_timeout=40).run()
    app.radio(key="source").set_value("Upload CSV").run()
    assert not app.exception
    assert any("Upload a daily-close CSV" in e.value for e in app.info)
