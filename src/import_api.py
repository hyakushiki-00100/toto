"""初期データの取り込み(CLAUDE.md §5 方法2)。API-Football の fixtures から results.csv 形式を作る。

使い方(自分のパソコンで実行。キーは環境変数に入れる。ファイルや引数には書かない):
    set API_FOOTBALL_KEY=あなたのキー
    python -m src.import_api --seasons 2023 2024 2025
1シーズン = 1リクエスト(無料枠は1日100回)。
結果は 90分時点のスコア(score.fulltime)を使う。PK戦・延長の結果は使わない(§2)。
チーム名が teams.csv に無いものが1つでもあれば、何も書かずに止まる(§3.3)。
"""
import argparse
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .io_check import check_results
from .teams import UnknownTeam, load_teams

BASE = "https://v3.football.api-sports.io"
J1_LEAGUE_ID = 98          # 確信度: 中。実行時に league.name を表示するので目で確認すること
JST = timezone(timedelta(hours=9))
FINISHED = {"FT", "AET", "PEN"}
HEADER = ["日付", "大会", "節", "ホーム", "アウェイ", "ホーム得点", "アウェイ得点",
          "備考", "出典URL", "取得日時", "入力方法", "状態"]


class ImportError_(RuntimeError):
    pass


def http_get(url, key, timeout=30):
    req = urllib.request.Request(url, headers={"x-apisports-key": key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ImportError_(f"API が HTTP {e.code} を返しました: {url}") from e
    except urllib.error.URLError as e:
        raise ImportError_(f"API に接続できません: {e.reason}") from e


def round_no(text):
    m = re.search(r"(\d+)\s*$", text or "")
    return m.group(1) if m else (text or "")


def convert(payload, url, teams, fetched_at):
    """API の応答 -> (行のリスト, 未登録のチーム名の集合, 未完了・欠測の件数メモ)。"""
    errs = payload.get("errors")
    if errs:   # 無料枠のシーズン制限などは、ここに文章で入る
        raise ImportError_(f"API がエラーを返しました: {errs}")
    rows, unknown, skipped, nofull = [], set(), 0, []
    for it in payload.get("response", []):
        fx, lg, tm, sc = it["fixture"], it["league"], it["teams"], it["score"]
        if fx["status"]["short"] not in FINISHED:
            skipped += 1
            continue
        ft = sc.get("fulltime") or {}
        if ft.get("home") is None or ft.get("away") is None:
            nofull.append(fx.get("id"))
            continue
        names = []
        for side in ("home", "away"):
            n = tm[side]["name"]
            try:
                names.append(teams.resolve(n))
            except UnknownTeam:
                unknown.add(n)
                names.append(None)
        status = fx["status"]["short"]
        note = {"FT": "", "AET": "延長あり(90分のスコアを記録)",
                "PEN": "PK決着(90分のスコアを記録)"}[status]
        d = datetime.fromisoformat(fx["date"]).astimezone(JST).date().isoformat()
        rows.append({"日付": d, "大会": "J1", "節": round_no(lg.get("round")),
                     "ホーム": names[0], "アウェイ": names[1],
                     "ホーム得点": ft["home"], "アウェイ得点": ft["away"], "備考": note,
                     "出典URL": url, "取得日時": fetched_at, "入力方法": "自動", "状態": "確定"})
    rows.sort(key=lambda r: (r["日付"], r["ホーム"] or ""))
    return rows, unknown, skipped, nofull


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, HEADER, lineterminator="\r\n")
        w.writeheader()
        w.writerows(rows)


def run(seasons, league, key, data_dir, out_dir, get=http_get, now=None, log=print):
    teams = load_teams(Path(data_dir) / "teams.csv")
    fetched_at = (now or datetime.now(JST)).strftime("%Y-%m-%d %H:%M")
    results, all_unknown = {}, set()
    for s in seasons:
        url = f"{BASE}/fixtures?league={league}&season={s}"
        payload = get(url, key)
        rows, unknown, skipped, nofull = convert(payload, url, teams, fetched_at)
        names = {(i["league"]["name"], i["league"]["season"]) for i in payload.get("response", [])}
        log(f"{s}: 取得 {len(payload.get('response', []))} 件 / 結果あり {len(rows)} 件 / "
            f"未実施等 {skipped} 件 / リーグ名 {sorted(names)}")
        if nofull:
            raise ImportError_(f"{s}: 90分のスコアが無い試合があります(fixture id: {nofull})。推測で埋めず中止します")
        if not payload.get("response"):
            raise ImportError_(f"{s}: 試合が0件です。リーグID({league})かシーズンの指定、無料枠の範囲を確認してください")
        all_unknown |= unknown
        results[s] = rows
    if all_unknown:
        raise ImportError_("data/teams.csv にないチーム名があります。対応を足してからやり直してください:\n  "
                           + "\n  ".join(sorted(all_unknown)))
    out = []
    for s, rows in results.items():
        p = Path(out_dir) / f"results_{s}.csv"
        write_rows(p, rows)
        probs = check_results(p, teams)
        if probs:
            raise ImportError_(f"{p.name} の入力チェックで問題:\n  " + "\n  ".join(map(str, probs[:20])))
        out.append(p)
        log(f"書き出し: {p}({len(rows)}試合, 入力チェック問題なし)")
    return out


def main(argv=None):
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", type=int, nargs="+", required=True)
    ap.add_argument("--league", type=int, default=J1_LEAGUE_ID)
    ap.add_argument("--data", default=str(root / "data"))
    ap.add_argument("--out", default=str(root / "data" / "import"))
    a = ap.parse_args(argv)
    key = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if not key:
        print("環境変数 API_FOOTBALL_KEY にキーを設定してください(ファイルには書かない)")
        return 2
    try:
        run(a.seasons, a.league, key, a.data, a.out)
    except ImportError_ as e:
        print("中止:", e)
        return 1
    print("\n取り込み結果は data/import/ にあります。results.csv へ統合する前に、中身を目で確認してください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
