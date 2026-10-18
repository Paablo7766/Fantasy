"""Resuelve nombres de futbolistas entre LALIGA Fantasy y las fuentes externas.

El pipeline normaliza diacríticos, mayúsculas, prefijos y una clave fonética
del castellano. La similitud mezcla Jaro-Winkler, Levenshtein y
``difflib.SequenceMatcher``. Si ``rapidfuzz`` está instalado, sustituye a las
dos primeras. El club y la posición deshacen homónimos. Por debajo de 0.85
no hay enlace automático: queda una auditoría o un mapeo manual.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from toolbox.cache import EntityStore

MATCH_THRESHOLD = 0.85
AMBIGUITY_GAP = 0.03
AUDIT_FLOOR = 0.60

_SPACE = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SUFFIXES = {"jr", "junior", "ii", "iii"}
_CLUB_NOISE = {"fc", "cf", "ud", "cd", "rcd", "sad", "club", "futbol", "football"}
_CLUB_ALIASES = {
    "r madrid": "real madrid",
    "rm": "real madrid",
    "real madrid cf": "real madrid",
    "barca": "barcelona",
    "fc barcelona": "barcelona",
    "atleti": "atletico madrid",
    "atletico": "atletico madrid",
    "athletic club": "athletic",
    "athletic bilbao": "athletic",
    "real betis": "betis",
    "betis": "betis",
    "rcd espanyol": "espanyol",
    "deportivo alaves": "alaves",
    "rayo vallecano": "rayo",
    "celta vigo": "celta",
    "real oviedo": "oviedo",
    "real sociedad": "real sociedad",
    "deportivo la coruna": "deportivo",
    "rc deportivo": "deportivo",
    "racing santander": "racing",
    "atletico de madrid": "atletico madrid",
    "atletico madrid": "atletico madrid",
}

_POSITION_EXACT = {
    "por": "POR",
    "gk": "POR",
    "goalkeeper": "POR",
    "portero": "POR",
    "def": "DEF",
    "df": "DEF",
    "cb": "DEF",
    "lb": "DEF",
    "rb": "DEF",
    "lwb": "DEF",
    "rwb": "DEF",
    "defender": "DEF",
    "defensa": "DEF",
    "mc": "MC",
    "mf": "MC",
    "dm": "MC",
    "cm": "MC",
    "am": "MC",
    "lm": "MC",
    "rm": "MC",
    "mid": "MC",
    "midfielder": "MC",
    "centrocampista": "MC",
    "del": "DEL",
    "fw": "DEL",
    "st": "DEL",
    "cf": "DEL",
    "lw": "DEL",
    "rw": "DEL",
    "ss": "DEL",
    "forward": "DEL",
    "striker": "DEL",
    "delantero": "DEL",
    "winger": "DEL",
}


def _rapidfuzz():
    try:
        from rapidfuzz.distance import JaroWinkler
        from rapidfuzz.distance import Levenshtein as RapidLevenshtein
    except ImportError:
        return None
    return JaroWinkler, RapidLevenshtein


_RAPID = _rapidfuzz()


@dataclass(frozen=True)
class CanonicalPlayer:
    player_id: str
    name: str | None
    nickname: str | None
    club: str | None
    position: str | None
    fantasy_price: int | None
    sale_price: int | None = None
    on_market: bool = False


@dataclass(frozen=True)
class ExternalRecord:
    source: str
    name: str
    external_id: str | None = None
    club: str | None = None
    position: str | None = None


@dataclass(frozen=True)
class MatchDecision:
    player_id: str
    source: str
    external_name: str
    external_id: str | None
    confidence: float
    manual: bool
    linked: bool
    reason: str | None = None


def strip_diacritics(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def normalize_name(text: str | None) -> str:
    if not text:
        return ""
    cleaned = strip_diacritics(text).lower().replace("ñ", "n")
    cleaned = _PUNCT.sub(" ", cleaned)
    tokens = [token for token in _SPACE.split(cleaned) if token and token not in _SUFFIXES]
    return " ".join(tokens)


def normalize_club(text: str | None) -> str:
    if not text:
        return ""
    cleaned = strip_diacritics(text).lower()
    cleaned = _PUNCT.sub(" ", cleaned)
    tokens = [token for token in cleaned.split() if token and token not in _CLUB_NOISE]
    folded = " ".join(tokens)
    return _CLUB_ALIASES.get(folded, folded)


def canonical_position(value: str | None) -> str | None:
    if not value:
        return None
    text = strip_diacritics(value).strip().lower()
    if text in _POSITION_EXACT:
        return _POSITION_EXACT[text]
    if "goalkeeper" in text or "portero" in text:
        return "POR"
    if "midfield" in text or "centrocamp" in text or "medio" in text:
        return "MC"
    if "back" in text or "defen" in text:
        return "DEF"
    if any(word in text for word in ("forward", "winger", "striker", "delantero", "ataque")):
        return "DEL"
    return None


def phonetic_key(text: str | None) -> str:
    """Clave fonética breve del castellano: h muda, v/b, z/c y geminadas."""
    name = normalize_name(text).replace(" ", "")
    if not name:
        return ""
    name = name.replace("ll", "y").replace("qu", "k")
    out: list[str] = []
    for index, char in enumerate(name):
        if char == "h":
            continue
        if char == "v":
            char = "b"
        elif char == "z":
            char = "s"
        elif char == "c" and index + 1 < len(name) and name[index + 1] in "ei":
            char = "s"
        elif char == "y":
            char = "i"
        if out and out[-1] == char:
            continue
        out.append(char)
    return "".join(out)


def levenshtein(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            insert = current[j - 1] + 1
            delete = previous[j] + 1
            replace = previous[j - 1] + (left_char != right_char)
            current.append(min(insert, delete, replace))
        previous = current
    return previous[-1]


def jaro(left: str, right: str) -> float:
    if left == right:
        return 1.0
    len_left, len_right = len(left), len(right)
    if len_left == 0 or len_right == 0:
        return 0.0
    match_distance = max(0, max(len_left, len_right) // 2 - 1)
    left_matches = [False] * len_left
    right_matches = [False] * len_right
    matches = 0
    for index, char in enumerate(left):
        start = max(0, index - match_distance)
        end = min(index + match_distance + 1, len_right)
        for cursor in range(start, end):
            if right_matches[cursor] or right[cursor] != char:
                continue
            left_matches[index] = True
            right_matches[cursor] = True
            matches += 1
            break
    if matches == 0:
        return 0.0
    transpositions = 0
    cursor = 0
    for index, char in enumerate(left):
        if not left_matches[index]:
            continue
        while not right_matches[cursor]:
            cursor += 1
        if right[cursor] != char:
            transpositions += 1
        cursor += 1
    transpositions /= 2
    return (
        matches / len_left
        + matches / len_right
        + (matches - transpositions) / matches
    ) / 3


def jaro_winkler(left: str, right: str, *, prefix_scale: float = 0.1) -> float:
    if _RAPID is not None:
        jaro_winkler_metric, _lev = _RAPID
        return float(jaro_winkler_metric.normalized_similarity(left, right))
    score = jaro(left, right)
    prefix = 0
    for left_char, right_char in zip(left, right):
        if left_char != right_char or prefix == 4:
            break
        prefix += 1
    return score + prefix * prefix_scale * (1 - score)


def _string_similarity(left: str, right: str) -> float:
    if _RAPID is not None:
        jaro_winkler_metric, levenshtein_metric = _RAPID
        jw = float(jaro_winkler_metric.normalized_similarity(left, right))
        lev = float(levenshtein_metric.normalized_similarity(left, right))
    else:
        jw = jaro_winkler(left, right)
        lev = 1.0 - levenshtein(left, right) / max(len(left), len(right), 1)
    sequence = SequenceMatcher(None, left, right).ratio()
    return (0.5 * jw) + (0.3 * lev) + (0.2 * sequence)


def _significant(text: str) -> list[str]:
    return [token for token in text.split() if len(token) > 1]


def name_similarity(left: str | None, right: str | None) -> float:
    normalized_left = normalize_name(left)
    normalized_right = normalize_name(right)
    if not normalized_left or not normalized_right:
        return 0.0
    if normalized_left == normalized_right:
        return 1.0
    string_score = _string_similarity(normalized_left, normalized_right)
    phonetic_left = phonetic_key(normalized_left)
    phonetic_right = phonetic_key(normalized_right)
    if phonetic_left == phonetic_right and len(phonetic_left) >= 4:
        string_score = max(string_score, 0.93)
    tokens_left = _significant(normalized_left)
    tokens_right = _significant(normalized_right)
    if not tokens_left or not tokens_right:
        return string_score
    overlap = set(tokens_left) & set(tokens_right)
    if not overlap:
        return string_score
    shorter, longer = (tokens_left, tokens_right) if len(tokens_left) <= len(tokens_right) else (tokens_right, tokens_left)
    shorter_text = normalized_left if len(tokens_left) <= len(tokens_right) else normalized_right
    initials = [token for token in shorter_text.split() if len(token) == 1]
    initial_bonus = 0.0
    used: set[str] = set()
    for initial in initials:
        for token in longer:
            if token in overlap or token in used:
                continue
            if token.startswith(initial):
                initial_bonus += 0.12
                used.add(token)
                break
    coverage = len(overlap) / min(len(tokens_left), len(tokens_right))
    if coverage == 1 and min(len(shorter), len(longer)) >= 2:
        token_score = min(1.0, 0.9 + initial_bonus)
    elif coverage == 1 and len(shorter) == 1:
        token_score = min(1.0, 0.74 + initial_bonus)
    else:
        token_score = min(1.0, 0.55 * coverage + initial_bonus)
    if len(shorter) == 1 and normalized_left != normalized_right:
        return max(token_score, min(string_score, token_score))
    return max(string_score, token_score)


def best_name_similarity(left_names: list[str | None], right: str | None) -> float:
    scores = [name_similarity(name, right) for name in left_names if name]
    return max(scores) if scores else 0.0


def score_pair(
    player: CanonicalPlayer,
    record: ExternalRecord,
    *,
    unique_tokens: bool = False,
) -> float:
    base = best_name_similarity([player.name, player.nickname], record.name)
    if base <= 0:
        return 0.0
    if unique_tokens and base < 0.9:
        base += 0.08
    club_left = normalize_club(player.club)
    club_right = normalize_club(record.club)
    if club_left and club_right:
        base += 0.05 if club_left == club_right else -0.28
    position_left = canonical_position(player.position)
    position_right = canonical_position(record.position)
    if position_left and position_right:
        base += 0.04 if position_left == position_right else -0.22
    if base < 0:
        return 0.0
    if base > 1:
        return 1.0
    return round(base, 4)


def _record_key(record: ExternalRecord) -> str:
    return record.external_id or normalize_name(record.name) + "|" + normalize_club(record.club)


def _tokens_unique(record: ExternalRecord, owners: dict[str, set[str]]) -> bool:
    tokens = _significant(normalize_name(record.name))
    if not tokens:
        return False
    return all(len(owners.get(token, ())) <= 1 for token in tokens)


class EntityResolver:
    def __init__(self, store: EntityStore) -> None:
        self._store = store

    def force_manual(
        self,
        *,
        player_id: str,
        source: str,
        external_name: str,
        external_id: str | None = None,
        club: str | None = None,
        position: str | None = None,
    ) -> dict[str, Any]:
        name = external_name.strip()
        if not player_id.strip() or not source.strip() or not name:
            raise ValueError("Un mapeo manual necesita player_id, source y external_name.")
        return self._store.put_link(
            player_id=player_id.strip(),
            source=source.strip(),
            external_name=name,
            external_id=external_id,
            club=club,
            position=canonical_position(position) or position,
            confidence=1.0,
            manual=True,
        )

    def audit(self, *, below: float = MATCH_THRESHOLD) -> list[dict[str, Any]]:
        rows = []
        for row in self._store.list_audits():
            if row["reason"] == "ambiguous" or float(row["confidence"]) < below:
                rows.append(row)
        return rows

    def link_source(self, players: list[CanonicalPlayer], records: list[ExternalRecord], source: str) -> list[MatchDecision]:
        pool = [record for record in records if record.source == source and record.name.strip()]
        self._store.clear_auto(source)
        self._store.clear_audits(source)
        manual = {link["player_id"]: link for link in self._store.manual_links(source)}
        owners: dict[str, set[str]] = {}
        for player in players:
            for label in (player.name, player.nickname):
                for token in _significant(normalize_name(label)):
                    owners.setdefault(token, set()).add(player.player_id)

        decisions: list[MatchDecision] = []
        used_records: set[str] = set()
        for player in players:
            link = manual.get(player.player_id)
            if link is None:
                continue
            decisions.append(
                MatchDecision(
                    player_id=player.player_id,
                    source=source,
                    external_name=str(link["external_name"]),
                    external_id=link["external_id"],
                    confidence=1.0,
                    manual=True,
                    linked=True,
                )
            )
            if link["external_id"]:
                used_records.add(str(link["external_id"]))

        ranked: list[tuple[float, CanonicalPlayer, ExternalRecord]] = []
        for player in players:
            if player.player_id in manual:
                continue
            for record in pool:
                unique = _tokens_unique(record, owners)
                ranked.append((score_pair(player, record, unique_tokens=unique), player, record))
        ranked.sort(key=lambda item: (-item[0], item[1].player_id, _record_key(item[2])))

        claimed_players: set[str] = set(manual)
        claimed_records: set[str] = set(used_records)
        best_for: dict[str, list[tuple[float, ExternalRecord]]] = {}
        for score, player, record in ranked:
            bucket = best_for.setdefault(player.player_id, [])
            if len(bucket) < 2:
                bucket.append((score, record))

        for player in players:
            if player.player_id in claimed_players:
                continue
            options = best_for.get(player.player_id, [])
            if not options:
                continue
            best_score, best_record = options[0]
            second_score = options[1][0] if len(options) > 1 else 0.0
            key = _record_key(best_record)
            ambiguous = best_score >= MATCH_THRESHOLD and best_score - second_score < AMBIGUITY_GAP
            if ambiguous or key in claimed_records or best_score < MATCH_THRESHOLD:
                reason = "ambiguous" if ambiguous else "low_confidence"
                if best_score >= AUDIT_FLOOR or ambiguous:
                    self._store.put_audit(
                        player_id=player.player_id,
                        source=source,
                        external_name=best_record.name,
                        candidate_name=player.nickname or player.name,
                        confidence=round(best_score, 4),
                        reason=reason,
                    )
                decisions.append(
                    MatchDecision(
                        player_id=player.player_id,
                        source=source,
                        external_name=best_record.name,
                        external_id=best_record.external_id,
                        confidence=round(best_score, 4),
                        manual=False,
                        linked=False,
                        reason=reason if best_score >= AUDIT_FLOOR or ambiguous else "unmatched",
                    )
                )
                continue
            self._store.put_link(
                player_id=player.player_id,
                source=source,
                external_name=best_record.name,
                external_id=best_record.external_id,
                club=best_record.club,
                position=canonical_position(best_record.position),
                confidence=round(best_score, 4),
                manual=False,
            )
            claimed_players.add(player.player_id)
            claimed_records.add(key)
            decisions.append(
                MatchDecision(
                    player_id=player.player_id,
                    source=source,
                    external_name=best_record.name,
                    external_id=best_record.external_id,
                    confidence=round(best_score, 4),
                    manual=False,
                    linked=True,
                )
            )
        return decisions

    def link_player(
        self,
        player: CanonicalPlayer,
        records: list[ExternalRecord],
        source: str,
    ) -> MatchDecision | None:
        """Elige, para un solo jugador, el mejor registro de una búsqueda ruidosa."""
        existing = self._store.get_link(player.player_id, source)
        if existing is not None and existing["manual"]:
            return MatchDecision(
                player_id=player.player_id,
                source=source,
                external_name=str(existing["external_name"]),
                external_id=existing["external_id"],
                confidence=1.0,
                manual=True,
                linked=True,
            )
        scored = [
            (score_pair(player, record), record)
            for record in records
            if record.name.strip()
        ]
        scored.sort(key=lambda item: (-item[0], item[1].name))
        if not scored:
            return None
        best_score, best_record = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0.0
        ambiguous = best_score >= MATCH_THRESHOLD and best_score - second < AMBIGUITY_GAP
        if ambiguous or best_score < MATCH_THRESHOLD:
            reason = "ambiguous" if ambiguous else "low_confidence"
            if best_score >= AUDIT_FLOOR or ambiguous:
                self._store.put_audit(
                    player_id=player.player_id,
                    source=source,
                    external_name=best_record.name,
                    candidate_name=player.nickname or player.name,
                    confidence=round(best_score, 4),
                    reason=reason,
                )
            return MatchDecision(
                player_id=player.player_id,
                source=source,
                external_name=best_record.name,
                external_id=best_record.external_id,
                confidence=round(best_score, 4),
                manual=False,
                linked=False,
                reason=reason,
            )
        stored = self._store.put_link(
            player_id=player.player_id,
            source=source,
            external_name=best_record.name,
            external_id=best_record.external_id,
            club=best_record.club,
            position=canonical_position(best_record.position),
            confidence=round(best_score, 4),
            manual=False,
        )
        return MatchDecision(
            player_id=player.player_id,
            source=source,
            external_name=str(stored["external_name"]),
            external_id=stored["external_id"],
            confidence=float(stored["confidence"]),
            manual=False,
            linked=True,
        )
