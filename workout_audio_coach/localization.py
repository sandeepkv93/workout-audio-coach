from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, replace


@dataclass(frozen=True)
class PhrasePack:
    starting_in: str = "Starting in"
    set_label: str = "Set {number}"
    rest: str = "Rest"
    workout_complete: str = "Workout complete"
    halfway: str = "Halfway"
    last_set: str = "Last set"
    seconds_left: str = "{seconds} seconds left"
    go: str = "Go"
    next_exercise: str = "Next: {name}"
    round_label: str = "Round {number}"

    def format_set(self, number: int) -> str:
        return self.set_label.format(number=number)

    def format_seconds_left(self, seconds: int) -> str:
        return self.seconds_left.format(seconds=seconds)

    def format_next_exercise(self, name: str) -> str:
        return self.next_exercise.format(name=name)

    def format_round(self, number: int) -> str:
        return self.round_label.format(number=number)


PHRASE_PACKS: dict[str, PhrasePack] = {
    "en": PhrasePack(),
    "es": PhrasePack(
        starting_in="Comenzando en",
        set_label="Serie {number}",
        rest="Descansa",
        workout_complete="Entrenamiento completo",
        halfway="A mitad de camino",
        last_set="Última serie",
        seconds_left="Quedan {seconds} segundos",
        go="Vamos",
        next_exercise="Siguiente: {name}",
        round_label="Ronda {number}",
    ),
    "fr": PhrasePack(
        starting_in="Début dans",
        set_label="Série {number}",
        rest="Repos",
        workout_complete="Entraînement terminé",
        halfway="À mi-chemin",
        last_set="Dernière série",
        seconds_left="Plus que {seconds} secondes",
        go="Allez",
        next_exercise="Suivant : {name}",
        round_label="Tour {number}",
    ),
    "de": PhrasePack(
        starting_in="Start in",
        set_label="Satz {number}",
        rest="Pause",
        workout_complete="Training abgeschlossen",
        halfway="Halbzeit",
        last_set="Letzter Satz",
        seconds_left="Noch {seconds} Sekunden",
        go="Los",
        next_exercise="Als Nächstes: {name}",
        round_label="Runde {number}",
    ),
    "it": PhrasePack(
        starting_in="Inizio tra",
        set_label="Serie {number}",
        rest="Riposo",
        workout_complete="Allenamento completato",
        halfway="A metà",
        last_set="Ultima serie",
        seconds_left="{seconds} secondi rimanenti",
        go="Via",
        next_exercise="Prossimo: {name}",
        round_label="Round {number}",
    ),
    "pt": PhrasePack(
        starting_in="Começando em",
        set_label="Série {number}",
        rest="Descanse",
        workout_complete="Treino concluído",
        halfway="Na metade",
        last_set="Última série",
        seconds_left="Faltam {seconds} segundos",
        go="Vai",
        next_exercise="Próximo: {name}",
        round_label="Rodada {number}",
    ),
    "hi": PhrasePack(
        starting_in="शुरू हो रहा है",
        set_label="सेट {number}",
        rest="आराम करें",
        workout_complete="वर्कआउट पूरा हुआ",
        halfway="आधा रास्ता पूरा",
        last_set="आखिरी सेट",
        seconds_left="{seconds} सेकंड बाकी",
        go="शुरू करें",
        next_exercise="अगला: {name}",
        round_label="राउंड {number}",
    ),
    "ja": PhrasePack(
        starting_in="開始まで",
        set_label="セット {number}",
        rest="休憩",
        workout_complete="ワークアウト完了",
        halfway="半分です",
        last_set="最後のセット",
        seconds_left="残り {seconds} 秒",
        go="スタート",
        next_exercise="次は {name}",
        round_label="ラウンド {number}",
    ),
    "ko": PhrasePack(
        starting_in="시작까지",
        set_label="세트 {number}",
        rest="휴식",
        workout_complete="운동 완료",
        halfway="절반 완료",
        last_set="마지막 세트",
        seconds_left="{seconds}초 남았습니다",
        go="시작",
        next_exercise="다음 운동: {name}",
        round_label="라운드 {number}",
    ),
    "zh": PhrasePack(
        starting_in="准备开始",
        set_label="第 {number} 组",
        rest="休息",
        workout_complete="训练完成",
        halfway="完成一半",
        last_set="最后一组",
        seconds_left="还剩 {seconds} 秒",
        go="开始",
        next_exercise="下一个：{name}",
        round_label="第 {number} 轮",
    ),
}

VALID_PHRASE_KEYS: frozenset[str] = frozenset(field.name for field in fields(PhrasePack))


def parse_phrase_override(raw: str) -> tuple[str, str]:
    if "=" not in raw:
        raise ValueError(f"invalid phrase override {raw!r}; expected KEY=VALUE")
    key, value = raw.split("=", 1)
    normalized_key = key.strip().replace("-", "_")
    if normalized_key not in VALID_PHRASE_KEYS:
        valid = ", ".join(sorted(VALID_PHRASE_KEYS))
        raise ValueError(f"unknown phrase key {key!r}; valid keys: {valid}")
    return normalized_key, value.strip()


def get_phrase_pack(
    language: str,
    overrides: Mapping[str, str] | None = None,
) -> PhrasePack:
    normalized = language.strip().lower().replace("_", "-")
    pack = PHRASE_PACKS.get(normalized)
    if pack is None and "-" in normalized:
        primary = normalized.split("-", 1)[0]
        pack = PHRASE_PACKS.get(primary)
    if pack is None:
        pack = PHRASE_PACKS["en"]

    if not overrides:
        return pack

    cleaned: dict[str, str] = {}
    for key, value in overrides.items():
        normalized_key = key.strip().replace("-", "_")
        if normalized_key not in VALID_PHRASE_KEYS:
            valid = ", ".join(sorted(VALID_PHRASE_KEYS))
            raise ValueError(f"unknown phrase key {key!r}; valid keys: {valid}")
        cleaned[normalized_key] = value
    return replace(pack, **cleaned)
