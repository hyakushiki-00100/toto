"""チーム名の対応表(data/teams.csv)の読み込みと名前の統一(CLAUDE.md §3.3)。

正式名・略称・別名のどれで入力されても、内部では正式名に統一する。
表にない名前は UnknownTeam を投げる(黙って新チームとして扱わない)。
"""
import csv
import unicodedata
from pathlib import Path


class UnknownTeam(ValueError):
    pass


class TeamTableError(ValueError):
    """teams.csv 自体の誤り(同じ名前が別チームに割り当てられている等)。"""


def norm(s):
    """表記ゆれ(全角/半角、空白)を吸収した比較用の文字列。"""
    return "".join(unicodedata.normalize("NFKC", s or "").split()).casefold()


class Teams:
    def __init__(self, rows):
        self.official = []          # 正式名の一覧(順序保持)
        self._map = {}              # norm(名前) -> 正式名
        for n, r in enumerate(rows, start=2):
            name = (r.get("正式名") or "").strip()
            if not name:
                raise TeamTableError(f"teams.csv {n}行目: 正式名が空です")
            if name in self.official:
                raise TeamTableError(f"teams.csv {n}行目: 正式名「{name}」が重複しています")
            self.official.append(name)
            names = [name, r.get("略称") or ""] + (r.get("別名") or "").split(";")
            for alias in names:
                key = norm(alias)
                if not key:
                    continue
                if self._map.get(key, name) != name:
                    raise TeamTableError(
                        f"teams.csv {n}行目: 「{alias}」は「{self._map[key]}」にも割り当てられています")
                self._map[key] = name

    def resolve(self, name):
        key = norm(name)
        if key not in self._map:
            raise UnknownTeam(name)
        return self._map[key]

    def __contains__(self, name):
        return norm(name) in self._map


def load_teams(path):
    with open(Path(path), encoding="utf-8-sig", newline="") as f:
        return Teams(list(csv.DictReader(f)))
