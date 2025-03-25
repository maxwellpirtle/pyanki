import enum
from dataclasses import dataclass
from dataclasses_json import dataclass_json

class DuplicateScope(enum.Enum):
    # A value of "deck" will only check
    # for duplicates in the target deck;
    # any other value checks all decks.
    CURRENT_DECK = "deck"
    ALL_DECKS = "all"

@dataclass_json
@dataclass
class DuplicateScopeOptions:
    deck_name: str
    duplicate_scope: DuplicateScope = DuplicateScope.ALL_DECKS
    check_children: bool = True
    check_all_models: bool = True

    @staticmethod
    def default(deck_name):
        return DuplicateScopeOptions(
            deck_name=deck_name,
        )
