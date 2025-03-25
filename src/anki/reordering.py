import enum
from dataclasses import dataclass
from dataclasses_json import dataclass_json

class Order(enum.Enum):
    ASCENDING = "ascending"
    DESCENDING = "descending"

class Column(enum.Enum):
    CUSTOM = "custom"
    ANSWER = "answer"
    CARD_MOD = "cardMod"
    CARDS = "template"
    DECK = "deck"
    DUE = "cardDue"
    EASE = "cardEase"
    LAPSES = "cardLapses"
    INTERVAL = "cardIvl"
    NOTE_CREATION = "noteCrt"
    NOTE_MOD = "noteMod"
    NOTE_TYPE = "note"
    ORIGINAL_POSITION = "originalPosition"
    QUESTION = "question"
    REPS = "cardReps"
    SORT_FIELD = "noteFld"
    TAGS = "noteTags"
    STABILITY = "stability"
    DIFFICULTY = "difficulty"
    RETRIEVABILITY = "retrievability"

@dataclass_json
@dataclass
class Reordering:
    order: Order = Order.ASCENDING
    columnId: Column = Column.DUE