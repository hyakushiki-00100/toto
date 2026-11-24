"""入力チェック(CLAUDE.md §3.4)。

問題があれば「どのファイルの何行目か」を日本語で表示して終了コード 1 で止まる。
行番号は Excel で見える行番号(見出し行が1行目、最初のデータが2行目)。
"""
import csv
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .teams import TeamTableError, Teams, UnknownTeam, load_teams

REASONS = {"負傷", "出場停止", "その他"}
CERTAINTY = {"確定", "濃厚", "不明"}
METHODS = {"自動", "手入力", "自動→手で修正"}
STATES = {"確定", "要確認"}

REQUIRED = {
    "results.csv": ["日付", "大会", "節", "ホーム", "アウェイ", "ホーム得点", "アウェイ得点"],
    "fixtures.csv": ["日付", "大会", "節", "ホーム", "アウェイ", "会場"],
    "absences.csv": ["対象試合の日付", "チーム", "選手名", "理由", "重要度", "確実さ"],
}
OPTIONAL_FILES = {
    "events.csv": ["チーム", "日付"],
    "others.csv": ["日付", "チーム"],
}


@dataclass(frozen=True)
class Problem:
    file: str
    row: int | None      # None = ファイル全体の問題
    message: str

    def __str__(self):
        where = self.file if self.row is None else f"{self.file} {self.row}行目"
        return f"[{where}] {self.message}"


def _n(s):
    return unicodedata.normalize("NFKC", s or "").strip()


def parse_date(s):
    """YYYY-MM-DD / YYYY/M/D / YYYY.M.D を受け付ける(Excel の表記ゆれ対策)。不正なら None。"""
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", _n(s))
    if not m:
        return None
    try:
        return date(*map(int, m.groups()))
    except ValueError:
        return None


def read_rows(path):
    """(見出し一覧, [(行番号, 辞書)])。完全な空行(Excel の残骸)は飛ばす。"""
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None:
            return [], []
        header = [h.strip() for h in header]
        rows = []
        for i, vals in enumerate(reader, start=2):
            if not any(v.strip() for v in vals):
                continue
            rows.append((i, {h: (vals[k].strip() if k < len(vals) else "")
                             for k, h in enumerate(header)}))
        return header, rows


class _Ctx:
    def __init__(self, name):
        self.name = name
        self.problems = []

    def add(self, row, msg):
        self.problems.append(Problem(self.name, row, msg))

    def team(self, teams, row, col, value):
        if not value:
            self.add(row, f"「{col}」が空欄です")
            return None
        try:
            return teams.resolve(value)
        except UnknownTeam:
            self.add(row, f"「{col}」のチーム名「{value}」が data/teams.csv にありません"
                          "(表記を直すか、teams.csv に追加してください)")
            return None

    def date(self, row, col, value):
        if not value:
            self.add(row, f"「{col}」が空欄です")
            return None
        d = parse_date(value)
        if d is None:
            self.add(row, f"「{col}」の日付「{value}」を読み取れません(例: 2026-08-07)")
        return d

    def meta(self, row, r, header):
        """自動入力の追加列(§3 冒頭)・§3.4 の「要確認」・§13.6 の出典必須。"""
        method = r.get("入力方法", "")
        state = r.get("状態", "")
        if method and method not in METHODS:
            self.add(row, f"「入力方法」は {'/'.join(sorted(METHODS))} のいずれかです(現在: 「{method}」)")
        if state and state not in STATES:
            self.add(row, f"「状態」は 確定/要確認 のいずれかです(現在: 「{state}」)")
        if state == "要確認":
            self.add(row, "状態が「要確認」です。確認して「確定」にするまで予想は作れません")
        if method.startswith("自動"):
            if not r.get("出典URL"):
                self.add(row, "自動で入れた行なのに「出典URL」が空欄です")
            if not r.get("取得日時"):
                self.add(row, "自動で入れた行なのに「取得日時」が空欄です")


def _header_ok(ctx, header, required):
    missing = [c for c in required if c not in header]
    for c in missing:
        ctx.add(None, f"必須の列「{c}」がありません")
    return not missing


def _score(ctx, row, col, v):
    v = _n(v)
    if v == "":
        ctx.add(row, f"「{col}」が空欄です(結果はスコアで入力します)")
        return None
    if not re.fullmatch(r"\d{1,2}", v):
        ctx.add(row, f"「{col}」は 0 以上の整数で入力してください(現在: 「{v}」)")
        return None
    return int(v)


def check_results(path, teams):
    ctx = _Ctx("results.csv")
    header, rows = read_rows(path)
    if not _header_ok(ctx, header, REQUIRED["results.csv"]):
        return ctx.problems
    seen = {}
    for i, r in rows:
        d = ctx.date(i, "日付", r["日付"])
        h = ctx.team(teams, i, "ホーム", r["ホーム"])
        a = ctx.team(teams, i, "アウェイ", r["アウェイ"])
        if not r["大会"]:
            ctx.add(i, "「大会」が空欄です")
        if h and a and h == a:
            ctx.add(i, f"ホームとアウェイが同じチーム「{h}」です")
        _score(ctx, i, "ホーム得点", r["ホーム得点"])
        _score(ctx, i, "アウェイ得点", r["アウェイ得点"])
        ctx.meta(i, r, header)
        if d and h and a:
            key = (d, h, a)
            if key in seen:
                ctx.add(i, f"{seen[key]}行目と同じ試合(日付・ホーム・アウェイ)が重複しています")
            else:
                seen[key] = i
    return ctx.problems


def _fixture_keys(path, teams):
    """fixtures.csv にある (日付, チーム) の集合。壊れた行は無視(別途 check_fixtures が指摘)。"""
    keys = set()
    _, rows = read_rows(path)
    for _, r in rows:
        d = parse_date(r.get("日付", ""))
        for col in ("ホーム", "アウェイ"):
            try:
                t = teams.resolve(r.get(col, ""))
            except UnknownTeam:
                continue
            if d:
                keys.add((d, t))
    return keys


def check_fixtures(path, teams):
    ctx = _Ctx("fixtures.csv")
    header, rows = read_rows(path)
    if not _header_ok(ctx, header, REQUIRED["fixtures.csv"]):
        return ctx.problems
    seen, team_day = {}, {}
    for i, r in rows:
        d = ctx.date(i, "日付", r["日付"])
        h = ctx.team(teams, i, "ホーム", r["ホーム"])
        a = ctx.team(teams, i, "アウェイ", r["アウェイ"])
        for col in ("大会", "節", "会場"):
            if not r[col]:
                ctx.add(i, f"「{col}」が空欄です")
        if h and a and h == a:
            ctx.add(i, f"ホームとアウェイが同じチーム「{h}」です")
        ctx.meta(i, r, header)
        if d and h and a:
            key = (d, h, a)
            if key in seen:
                ctx.add(i, f"{seen[key]}行目と同じ試合(日付・ホーム・アウェイ)が重複しています")
            else:
                seen[key] = i
            for t in {h, a}:
                if (d, t) in team_day:
                    ctx.add(i, f"{team_day[(d, t)]}行目と同じ日に「{t}」の試合が2つあります")
                else:
                    team_day[(d, t)] = i
    return ctx.problems


def check_absences(path, teams, fixture_keys=None):
    ctx = _Ctx("absences.csv")
    header, rows = read_rows(path)
    if not _header_ok(ctx, header, REQUIRED["absences.csv"]):
        return ctx.problems
    seen = {}
    for i, r in rows:
        d = ctx.date(i, "対象試合の日付", r["対象試合の日付"])
        t = ctx.team(teams, i, "チーム", r["チーム"])
        if not r["選手名"]:
            ctx.add(i, "「選手名」が空欄です")
        if r["理由"] not in REASONS:
            ctx.add(i, f"「理由」は 負傷/出場停止/その他 のいずれかです(現在: 「{r['理由']}」)")
        imp = _n(r["重要度"])
        if imp not in {"1", "2", "3"}:
            ctx.add(i, f"「重要度」は 1〜3 の整数です(現在: 「{r['重要度']}」)")
        if r["確実さ"] not in CERTAINTY:
            ctx.add(i, f"「確実さ」は 確定/濃厚/不明 のいずれかです(現在: 「{r['確実さ']}」)")
        ctx.meta(i, r, header)
        if d and t:
            if fixture_keys is not None and (d, t) not in fixture_keys:
                ctx.add(i, f"{d}に「{t}」の試合が fixtures.csv にありません"
                           "(日付かチーム名の誤り、または fixtures.csv の入力漏れ)")
            key = (d, t, _n(r["選手名"]))
            if r["選手名"] and key in seen:
                ctx.add(i, f"{seen[key]}行目と同じ選手(同じ日付・チーム)が重複しています")
            else:
                seen[key] = i
    return ctx.problems


def check_optional(path, teams, name):
    ctx = _Ctx(name)
    header, rows = read_rows(path)
    if not _header_ok(ctx, header, OPTIONAL_FILES[name]):
        return ctx.problems
    for i, r in rows:
        ctx.date(i, "日付", r["日付"])
        ctx.team(teams, i, "チーム", r["チーム"])
    return ctx.problems


def check_all(data_dir):
    data_dir = Path(data_dir)
    tpath = data_dir / "teams.csv"
    if not tpath.exists():
        return [Problem("teams.csv", None, "ファイルがありません")]
    try:
        teams = load_teams(tpath)
    except TeamTableError as e:
        return [Problem("teams.csv", None, str(e))]
    problems = []
    for name in REQUIRED:
        if not (data_dir / name).exists():
            problems.append(Problem(name, None, "ファイルがありません"))
    fx = data_dir / "fixtures.csv"
    if fx.exists():
        problems += check_fixtures(fx, teams)
    if (data_dir / "results.csv").exists():
        problems += check_results(data_dir / "results.csv", teams)
    if (data_dir / "absences.csv").exists():
        keys = None
        if fx.exists():
            keys = _fixture_keys(fx, teams)
        problems += check_absences(data_dir / "absences.csv", teams, keys)
    for name in OPTIONAL_FILES:
        if (data_dir / name).exists():
            problems += check_optional(data_dir / name, teams, name)
    return problems


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    data_dir = argv[0] if argv else Path(__file__).resolve().parent.parent / "data"
    problems = check_all(data_dir)
    if problems:
        print(f"入力に {len(problems)} 件の問題があります。直してからやり直してください。\n")
        for p in problems:
            print(" ", p)
        return 1
    print("入力チェック: 問題なし")
    return 0


if __name__ == "__main__":
    sys.exit(main())
