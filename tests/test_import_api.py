import csv

import pytest

from src import import_api as ia
from src.teams import load_teams
from tests.conftest import ROOT


def fx(i, status, home, away, ft, rnd="Regular Season - 3", date="2025-03-01T10:00:00+00:00"):
    return {"fixture": {"id": i, "date": date, "status": {"short": status}},
            "league": {"name": "J1 League", "season": 2025, "round": rnd},
            "teams": {"home": {"name": home}, "away": {"name": away}},
            "score": {"fulltime": {"home": ft[0], "away": ft[1]} if ft else {"home": None, "away": None},
                      "extratime": {"home": None, "away": None}, "penalty": {"home": 5, "away": 4}},
            "goals": {"home": 9, "away": 9}}


def payload(*items, errors=None):
    return {"errors": errors or [], "response": list(items)}


def go(tmp_path, pl, seasons=(2025,)):
    return ia.run(list(seasons), 98, "k", ROOT / "data", tmp_path, get=lambda u, k: pl, log=lambda *_: None)


def test_converts_90min_score_and_jst_date(tmp_path):
    pl = payload(fx(1, "FT", "Urawa Reds", "Kashima Antlers", (2, 1), date="2025-03-01T16:00:00+00:00"),
                 fx(2, "PEN", "Gamba Osaka", "Cerezo Osaka", (1, 1)),     # goals は 9-9 だが fulltime を使う
                 fx(3, "NS", "FC Tokyo", "Kashiwa Reysol", None))
    (p,) = go(tmp_path, pl)
    rows = list(csv.DictReader(open(p, encoding="utf-8-sig")))
    assert len(rows) == 2                                   # 未実施は入らない
    r = {x["ホーム"]: x for x in rows}
    assert r["浦和レッズ"]["日付"] == "2025-03-02"           # 16:00 UTC = 翌01:00 JST
    assert r["浦和レッズ"]["ホーム得点"] == "2" and r["浦和レッズ"]["節"] == "3"
    assert r["ガンバ大阪"]["ホーム得点"] == "1" and "PK" in r["ガンバ大阪"]["備考"]
    assert r["浦和レッズ"]["入力方法"] == "自動" and r["浦和レッズ"]["出典URL"].startswith("https://")


def test_unknown_team_stops_without_writing(tmp_path):
    pl = payload(fx(1, "FT", "Urawa Reds", "Mystery FC", (0, 0)))
    with pytest.raises(ia.ImportError_, match="Mystery FC"):
        go(tmp_path, pl)
    assert not list(tmp_path.glob("*.csv"))


def test_api_errors_and_empty_stop(tmp_path):
    with pytest.raises(ia.ImportError_, match="plan"):
        go(tmp_path, payload(errors={"plan": "Free plans do not have access to this season"}))
    with pytest.raises(ia.ImportError_, match="0件"):
        go(tmp_path, payload())


def test_missing_fulltime_is_not_guessed(tmp_path):
    with pytest.raises(ia.ImportError_, match="90分"):
        go(tmp_path, payload(fx(7, "FT", "Urawa Reds", "Kashima Antlers", None)))


def test_missing_key_exits_2(monkeypatch):
    monkeypatch.delenv("API_FOOTBALL_KEY", raising=False)
    assert ia.main(["--seasons", "2025"]) == 2


def test_all_english_aliases_resolve():
    t = load_teams(ROOT / "data/teams.csv")
    assert t.resolve("Urawa Red Diamonds") == "浦和レッズ"
    assert t.resolve("Yokohama F. Marinos") == "横浜F・マリノス"
