from src import io_check
from src.teams import TeamTableError, Teams, UnknownTeam, load_teams
from tests.conftest import ROOT, write

RH = "日付,大会,節,ホーム,アウェイ,ホーム得点,アウェイ得点,備考,出典URL,取得日時,入力方法,状態"
FH = "日付,大会,節,ホーム,アウェイ,会場,出典URL,取得日時,入力方法,状態"
AH = "対象試合の日付,チーム,選手名,理由,重要度,確実さ,出典URL,取得日時,入力方法,状態"


def msgs(data):
    return [str(p) for p in io_check.check_all(data)]


def test_template_passes():
    assert io_check.check_all(ROOT / "data") == []


def test_templates_have_bom():
    for p in (ROOT / "data").glob("*.csv"):
        assert p.read_bytes().startswith(b"\xef\xbb\xbf"), p.name


def test_teams_table_is_20_and_resolves_all_forms():
    t = load_teams(ROOT / "data/teams.csv")
    assert len(t.official) == 20
    assert t.resolve("浦和") == t.resolve("浦和レッズ") == "浦和レッズ"
    assert t.resolve("ＦＣ東京") == "FC東京"          # 全角
    assert t.resolve(" 川崎 F ") == "川崎フロンターレ"  # 空白


def test_ambiguous_or_unknown_names_are_rejected():
    t = load_teams(ROOT / "data/teams.csv")
    for bad in ["東京", "横浜", "新潟", ""]:
        try:
            t.resolve(bad)
            assert False, bad
        except UnknownTeam:
            pass


def test_alias_collision_in_teams_csv_is_error():
    rows = [{"正式名": "A", "略称": "x", "別名": ""}, {"正式名": "B", "略称": "x", "別名": ""}]
    try:
        Teams(rows)
        assert False
    except TeamTableError as e:
        assert "2" in str(e) or "3" in str(e)


def test_results_ok_with_aliases_and_slash_date(data):
    write(data / "results.csv", RH, ["2026/8/7,J1,1,浦和,鹿島アントラーズ,2,１,,,,手入力,確定"])
    assert msgs(data) == []


def test_results_errors_report_file_and_row(data):
    write(data / "results.csv", RH, [
        "2026-08-07,J1,1,浦和,鹿島,2,1,,,,手入力,確定",      # 2行目 OK
        "2026-08-07,J1,1,浦和,鹿島,2,1,,,,手入力,確定",      # 3行目 重複
        "2026-08-08,J1,1,東京,鹿島,2,1,,,,手入力,確定",      # 4行目 チーム名
        "2026-08-08,J1,1,柏,柏,2,1,,,,手入力,確定",          # 5行目 同一チーム
        "2026-08-09,J1,1,福岡,広島,,1,,,,手入力,確定",       # 6行目 スコア空欄
        "2026-13-09,J1,1,福岡,広島,1,1,,,,手入力,確定",      # 7行目 不正日付
        "2026-08-09,J1,1,福岡,広島,-1,1,,,,手入力,確定",     # 8行目 負数
    ])
    m = msgs(data)
    assert any("results.csv 3行目" in x and "重複" in x and "2行目" in x for x in m)
    assert any("results.csv 4行目" in x and "東京" in x for x in m)
    assert any("results.csv 5行目" in x and "同じチーム" in x for x in m)
    assert any("results.csv 6行目" in x and "ホーム得点" in x for x in m)
    assert any("results.csv 7行目" in x and "日付" in x for x in m)
    assert any("results.csv 8行目" in x and "整数" in x for x in m)
    assert not any("results.csv 2行目" in x for x in m)


def test_needs_review_blocks(data):
    write(data / "results.csv", RH, ["2026-08-07,J1,1,浦和,鹿島,2,1,,http://x,2026-08-10 09:00,自動,要確認"])
    assert any("要確認" in x for x in msgs(data))


def test_auto_rows_require_source_and_timestamp(data):
    write(data / "results.csv", RH, ["2026-08-07,J1,1,浦和,鹿島,2,1,,,,自動,確定"])
    m = msgs(data)
    assert any("出典URL" in x for x in m) and any("取得日時" in x for x in m)


def test_blank_excel_rows_ignored(data):
    write(data / "results.csv", RH, [",,,,,,,,,,,", "2026-08-07,J1,1,浦和,鹿島,2,1,,,,手入力,確定"])
    assert msgs(data) == []


def test_missing_column_and_missing_file(data):
    write(data / "results.csv", "日付,大会,節,ホーム,アウェイ", [])
    (data / "fixtures.csv").unlink()
    m = msgs(data)
    assert any("results.csv" in x and "ホーム得点" in x for x in m)
    assert any("fixtures.csv" in x and "ファイルがありません" in x for x in m)


def test_fixtures_duplicate_and_double_booking(data):
    write(data / "fixtures.csv", FH, [
        "2026-08-15,J1,2,浦和,鹿島,埼玉,,,手入力,確定",
        "2026-08-15,J1,2,浦和,鹿島,埼玉,,,手入力,確定",     # 重複
        "2026-08-15,J1,2,柏,鹿島,三協,,,手入力,確定",       # 鹿島が同日2試合
    ])
    m = msgs(data)
    assert any("fixtures.csv 3行目" in x and "重複" in x for x in m)
    assert any("fixtures.csv 4行目" in x and "鹿島アントラーズ" in x for x in m)


def test_absences_validation(data):
    write(data / "fixtures.csv", FH, ["2026-08-15,J1,2,浦和,鹿島,埼玉,,,手入力,確定"])
    write(data / "absences.csv", AH, [
        "2026-08-15,浦和,A選手,負傷,3,確定,,,手入力,確定",     # OK
        "2026-08-15,浦和,B選手,けが,5,たぶん,,,手入力,確定",   # 理由/重要度/確実さ
        "2026-08-22,浦和,C選手,負傷,2,確定,,,手入力,確定",     # 対象試合なし
        "2026-08-15,浦和,A選手,負傷,3,確定,,,手入力,確定",     # 重複
    ])
    m = msgs(data)
    assert not any("absences.csv 2行目" in x for x in m)
    assert sum("absences.csv 3行目" in x for x in m) == 3
    assert any("absences.csv 4行目" in x and "fixtures.csv にありません" in x for x in m)
    assert any("absences.csv 5行目" in x and "重複" in x for x in m)


def test_cli_exit_codes_and_japanese_output(data, capsys):
    assert io_check.main([str(data)]) == 0
    write(data / "results.csv", RH, ["2026-08-07,J1,1,東京,鹿島,2,1,,,,手入力,確定"])
    assert io_check.main([str(data)]) == 1
    out = capsys.readouterr().out
    assert "results.csv 2行目" in out and "東京" in out


def test_check_is_deterministic(data):
    write(data / "results.csv", RH, ["2026-08-07,J1,1,東京,鹿島,2,1,,,,手入力,確定"])
    assert msgs(data) == msgs(data)
