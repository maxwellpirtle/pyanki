import json
import httpx
from logging import log, INFO
from typing import List
from contextlib import contextmanager, asynccontextmanager

from anki.note import Note
from anki.reordering import Reordering
from anki.resource import Resource
from anki.errors import APIException as AnkiAPIException
from anki.errors import UnexpectedAPIResponse as AnkiAPIUnexpectedResponse
from anki.batch import BatchManager, DeferredResult

class BaseClient:
    def __init__(
        self, *,
        version: int = 6,
        anki_url: str = "http://localhost:8765",
        sync_on_dtor: bool = False,
        log_api_calls: bool = False
    ):
        """Constructs a new client
        :param version: the AnkiConnect version number (defaults to 6 [latest])
        :param anki_url: the endpoint to connect to the AnkiConnect server (defaults to "http://localhost:8765")
        :param sync_on_dtor: whether a `sync` call should be sent automatically
        when the instance is deleted. This is equivalent to hitting the "Sync" button
        in the Anki GUI.
        :param log_api_calls: whether logging should occur for each HTTP request
        """
        self.version = version
        self.anki_url = anki_url
        self.sync_on_dtor = sync_on_dtor
        self.log_api_calls = log_api_calls
        self.batcher = None

    @contextmanager
    def make_batch(self):
        old_batcher = self.batcher
        if self.batcher is None:
            self.batcher = BatchManager(self)
        yield self.batcher
        self.batcher = old_batcher

class AsyncClient(BaseClient):
    """A small wrapper around the AnkiConnect API

    The AnkiConnect API ("https://git.sr.ht/~foosoft/anki-connect") runs
    a local HTTP server on port 8765 that allows users to modify and query
    the local Anki database. All actions supported by the Anki GUI are also
    supported by AnkiConnect.

    To interact with AnkiConnect, instantiate an instance of `AnkiConnect`

    ```python
    from anki.connect import AsyncClient
    ac_client = AsyncClient()
    card_ids = await ac_client.find_cards('deck:*')
    cards_are_due = await ac_client.are_due(card_ids)
    ```

    The AnkiConnect API also supports submitting batches of
    commands using the `multi` action. This is supported by creating
    an `anki.BatchManager` instance. You shouldn't need to construct
    one manually: instead, use the `send_batch` and `make_batch` methods:

    ```
    with ac_client.make_batch() as batch:
        ease_factors = await batch.get_ease_factors(card_ids)

    async with ac_client.send_batch() as batch:
        ease_factors2 = await batch.get_ease_factors(card_ids)

    print(await ease_factors)
    print(await ease_factors2)
    ```

    The difference between the two methods is that in the latter case the
    HTTP request will be made immediately after exiting the `with` statement,
    while in the former case, only the first `await` of any result will trigger
    the request. Note that currently an extra `await` is needed even in the
    `make_batch()` case even though the request happens synchronously before
    the member is accessed. This is because in principle you could be allowed
    to `await` the result within the `with` statement, and trigger a (partial)
    `multi` action request early.
    """

    @asynccontextmanager
    async def send_batch(self):
        old_batcher = self.batcher
        if self.batcher is None:
            self.batcher = BatchManager(self)
        yield self.batcher
        await self.batcher.async_dispatch()
        self.batcher = old_batcher

    async def invoke(self, action, **params):
        if self.batcher:
            return self.batcher.add_action(self.version, action, **params)
        else:
            return await self.invoke_no_batch(action, **params)

    async def invoke_no_batch(self, action, **params):
        request_body = BatchManager.make_request(self.version, action, **params)
        payload = json.dumps(request_body, indent=2)
        if self.log_api_calls:
            log(INFO, f'Request: \n{payload}')
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.anki_url, json=request_body)
                response.raise_for_status()
            except httpx.RequestError as exc:
                raise AnkiAPIException(
                    f"An error occurred while requesting {exc.request.url!r}."
                ) from exc
            except httpx.HTTPStatusError as exc:
                raise AnkiAPIException(
                    f"HTTP error occurred: {exc.response.status_code} {exc.response.text}"
                ) from exc
        response = response.json()
        if self.log_api_calls:
            log(INFO, f'Response: \n{json.dumps(response, indent=2)}')
        parsed_response = BatchManager.parse_response(response)
        if isinstance(parsed_response, Exception):
            raise parsed_response
        return parsed_response

    # MARK: Card Actions
    async def get_ease_factors(self, cards):
        """Retrieves the ease factors for the given cards.

        :param cards: A list of card IDs for which to retrieve ease factors.
        :return: A list of ease factors in the same order as the provided card IDs.
        :raises ValueError: If the input or output data types are incorrect.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(cards, list) or not all(isinstance(card, int) for card in cards):
            raise ValueError("Argument 'cards' must be a list of integers.")

        result = await self.invoke("getEaseFactors", cards=cards)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(factor, (bool, type(None))) for factor in result):
            raise AnkiAPIUnexpectedResponse("API response for 'getEaseFactors' must be a list of integers or None")

        return result

    async def set_ease_factors(self, cards, ease_factors):
        """Sets the ease factors for the given cards.

        :param cards: A list of card IDs to update.
        :param ease_factors: A list of ease factors corresponding to the card IDs.
        :return: A list of booleans indicating success for each card.
        :raises ValueError: If the input or output data types are incorrect.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(cards, list) or not all(isinstance(card, int) for card in cards):
            raise ValueError("Argument 'cards' must be a list of integers.")

        if not isinstance(ease_factors, list) or not all(isinstance(factor, int) for factor in ease_factors):
            raise ValueError("Argument 'ease_factors' must be a list of integers.")

        if len(cards) != len(ease_factors):
            raise ValueError("Arguments 'cards' and 'ease_factors' must have the same length.")

        result = await self.invoke("setEaseFactors", cards=cards, easeFactors=ease_factors)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(success, bool) for success in result):
            raise AnkiAPIUnexpectedResponse("API response for 'setEaseFactors' must be a list of booleans.")

        return result

    async def suspend(self, cards):
        """Suspends the given cards by their IDs.

        :param cards: A list of card IDs to suspend.
        :return: True if at least one card was successfully suspended, otherwise False.
        :raises ValueError: If the input data type is incorrect or the API response is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(cards, list) or not all(isinstance(card, int) for card in cards):
            raise ValueError("Argument 'cards' must be a list of integers.")

        result = await self.invoke("suspend", cards=cards)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'suspend' must be a boolean.")

        return result

    async def unsuspend(self, cards):
        """Unsuspends the given cards by their IDs.

        :param cards: A list of card IDs to unsuspend.
        :return: True if at least one card was successfully unsuspended, otherwise False.
        :raises ValueError: If the input data type is incorrect or the API response is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(cards, list) or not all(isinstance(card, int) for card in cards):
            raise ValueError("Argument 'cards' must be a list of integers.")

        result = await self.invoke("unsuspend", cards=cards)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'unsuspend' must be a boolean.")

        return result

    async def suspended(self, card):
        """Checks if a given card is suspended by its ID.

        :param card: The ID of the card to check.
        :return: True if the card is suspended, otherwise False.
        :raises ValueError: If the input data type is incorrect or the API response is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(card, int):
            raise ValueError("Argument 'card' must be an integer.")

        result = await self.invoke("suspended", card=card)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'suspended' must be a boolean.")

        return result

    async def are_suspended(self, cards):
        """Checks if the given cards are suspended.

        :param cards: A list of card IDs to check.
        :return: A list indicating whether each card is suspended (True, False, or None if card doesn’t exist).
        :raises ValueError: If the input data type is incorrect or the API response is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(cards, list) or not all(isinstance(card, int) for card in cards):
            raise ValueError("Argument 'cards' must be a list of integers.")

        result = await self.invoke("areSuspended", cards=cards)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(r, (bool, type(None))) for r in result):
            raise AnkiAPIUnexpectedResponse("API response for 'areSuspended' must be a list of booleans or None values.")

        return result

    async def are_due(self, cards):
        """Checks if the given cards are due.

        :param cards: A list of card IDs to check.
        :return: A list indicating whether each card is due (True or False).
        :raises ValueError: If the input data type is incorrect or the API response is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(cards, list) or not all(isinstance(card, int) for card in cards):
            raise ValueError("Argument 'cards' must be a list of integers.")

        result = await self.invoke("areDue", cards=cards)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(r, bool) for r in result):
            raise AnkiAPIUnexpectedResponse("API response for 'areDue' must be a list of booleans.")

        return result

    async def get_intervals(self, cards, complete=False):
        """Retrieves the intervals for the given cards.

        :param cards: A list of card IDs to check.
        :param complete: If True, returns all intervals for each card; otherwise, only the most recent intervals.
        :return: A list of intervals (in days or seconds) or a 2D list of intervals if complete is True.
        :raises ValueError: If the input data type is incorrect or the API response is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(cards, list) or not all(isinstance(card, int) for card in cards):
            raise ValueError("Argument 'cards' must be a list of integers.")

        if not isinstance(complete, bool):
            raise ValueError("Argument 'complete' must be a boolean.")

        result = await self.invoke("getIntervals", cards=cards, complete=complete)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list):
            raise AnkiAPIUnexpectedResponse("API response for 'getIntervals' must be a list.")

        if complete:
            if not all(isinstance(intervals, list) and all(isinstance(i, int) for i in intervals) for intervals in result):
                raise AnkiAPIUnexpectedResponse("API response for 'getIntervals' with complete=True must be a 2D list of integers.")
        else:
            if not all(isinstance(interval, int) for interval in result):
                raise AnkiAPIUnexpectedResponse("API response for 'getIntervals' with complete=False must be a list of integers.")
        return result

    async def find_cards(self, query):
        """Finds card IDs based on a given query.

        :param query: The search query string to find cards.
        :return: A list of card IDs matching the query.
        :raises ValueError: If the input data type is incorrect or the API response is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(query, str):
            raise ValueError("Argument 'query' must be a string.")

        result = await self.invoke("findCards", query=query)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(card_id, int) for card_id in result):
            raise AnkiAPIUnexpectedResponse("API response for 'findCards' must be a list of integers.")

        return result

    async def cards_to_notes(self, cards):
        """Retrieves note IDs for the given card IDs.

        :param cards: A list of card IDs to map to note IDs.
        :return: A list of unique note IDs corresponding to the card IDs.
        :raises ValueError: If the input data type is incorrect or the API response is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(cards, list) or not all(isinstance(card, int) for card in cards):
            raise ValueError("Argument 'cards' must be a list of integers.")

        result = await self.invoke("cardsToNotes", cards=cards)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(note_id, int) for note_id in result):
            raise AnkiAPIUnexpectedResponse("API response for 'cardsToNotes' must be a list of integers.")

        return result

    async def cards_mod_time(self, cards):
        """Retrieves modification times for the given card IDs.

        :param cards: A list of card IDs to retrieve modification times for.
        :return: A list of dictionaries, each containing a card ID and its modification time.
        :raises ValueError: If the input data type is incorrect or the API response is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(cards, list) or not all(isinstance(card, int) for card in cards):
            raise ValueError("Argument 'cards' must be a list of integers.")

        result = await self.invoke("cardsModTime", cards=cards)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(
            not entry or
            ((isinstance(entry, dict) and "cardId" in entry and "mod" in entry) and
            isinstance(entry["cardId"], int) and isinstance(entry["mod"], int)) for entry in result
        ):
            raise AnkiAPIUnexpectedResponse("API response for 'cardsModTime' must be a list of dictionaries with 'cardId' and 'mod' keys.")

        return result

    async def cards_info(self, cards: List[int]):
        """Retrieves detailed information for the given card IDs.

        :param cards: A list of card IDs to retrieve information for.
        :return: A list of dictionaries containing detailed information for each card.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(cards, list) or not all(isinstance(card, int) for card in cards):
            raise ValueError("Argument 'cards' must be a list of integers.")

        result = await self.invoke("cardsInfo", cards=cards)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list):
            raise AnkiAPIUnexpectedResponse("API response for 'cardsInfo' must be a list of dictionaries.")

        for card_info in result:
            if not card_info:
                continue

            required_keys = {
                "answer", "question", "deckName", "modelName", "fieldOrder", "fields",
                "css", "cardId", "interval", "note", "ord", "type", "queue", "due",
                "reps", "lapses", "left", "mod"
            }

            if not isinstance(card_info, dict) or not required_keys.issubset(card_info.keys()):
                raise AnkiAPIUnexpectedResponse(
                    "Each entry in the API response for 'cardsInfo' must be a dictionary containing all required keys."
                )

            if not isinstance(card_info["cardId"], int) or not isinstance(card_info["mod"], int):
                raise AnkiAPIUnexpectedResponse(
                    "Fields 'cardId' and 'mod' in 'cardsInfo' response must be integers."
                )
        return result

    async def forget_cards(self, cards):
        """Forgets the given cards, making them new again.

        :param cards: A list of card IDs to forget.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(cards, list) or not all(isinstance(card, int) for card in cards):
            raise ValueError("Argument 'cards' must be a list of integers.")

        result = await self.invoke("forgetCards", cards=cards)

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'forgetCards' must be null.")

        return result

    async def relearn_cards(self, cards):
        """Marks the given cards as "relearning".

        :param cards: A list of card IDs to mark as relearning.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(cards, list) or not all(isinstance(card, int) for card in cards):
            raise ValueError("Argument 'cards' must be a list of integers.")

        result = await self.invoke("relearnCards", cards=cards)

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'relearnCards' must be null.")

        return result

    async def answer_cards(self, answers):
        """Answers cards with the specified ease values.

        :param answers: A list of dictionaries, each containing 'cardId' (int) and 'ease' (int between 1 and 4).
        :return: A list of booleans indicating success (True) or failure (False) for each card.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(answers, list) or not all(
            isinstance(answer, dict) and
            isinstance(answer.get("cardId"), int) and
            isinstance(answer.get("ease"), int) and 1 <= answer["ease"] <= 4
            for answer in answers
        ):
            raise ValueError(
                "Argument 'answers' must be a list of dictionaries with 'cardId' as an integer and 'ease' as an integer between 1 and 4."
            )

        result = await self.invoke("answerCards", answers=answers)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(res, bool) for res in result):
            raise AnkiAPIUnexpectedResponse("API response for 'answerCards' must be a list of booleans.")

        return result

    async def deck_names(self):
        """Gets the complete list of deck names for the current user.

        :return: A list of deck names.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = await self.invoke("deckNames")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(deck, str) for deck in result):
            raise AnkiAPIUnexpectedResponse("API response for 'deckNames' must be a list of strings.")

        return result

    async def deck_names_and_ids(self):
        """Gets the complete list of deck names and their respective IDs for the current user.

        :return: A dictionary with deck names as keys and their IDs as values.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = await self.invoke("deckNamesAndIds")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, dict) or not all(
            isinstance(deck, str) and isinstance(deck_id, int) for deck, deck_id in result.items()
        ):
            raise AnkiAPIUnexpectedResponse("API response for 'deckNamesAndIds' must be a dictionary with strings as keys and integers as values.")

        return result

    async def get_decks(self, cards):
        """Gets the decks and their respective card IDs for the given card IDs.

        :param cards: A list of card IDs to query.
        :return: A dictionary with deck names as keys and lists of card IDs as values.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(cards, list) or not all(isinstance(card, int) for card in cards):
            raise ValueError("Argument 'cards' must be a list of integers.")

        result = await self.invoke("getDecks", cards=cards)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, dict) or not all(
            isinstance(deck, str) and isinstance(cards_list, list) and all(isinstance(card, int) for card in cards_list)
            for deck, cards_list in result.items()
        ):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'getDecks' must be a dictionary with strings as keys and lists of integers as values."
            )

        return result

    async def create_deck(self, deck: str):
        """Creates a new empty deck.

        :param deck: The name of the deck to create.
        :return: The ID of the newly created deck.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(deck, str):
            raise ValueError("Argument 'deck' must be a string.")

        result = await self.invoke("createDeck", deck=deck)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, int):
            raise AnkiAPIUnexpectedResponse("API response for 'createDeck' must be an integer.")

        return result

    async def get_cards_in_deck(self, deck: str):
        return await self.find_cards(f"deck:\"{deck}\"")

    async def get_notes_in_deck(self, deck: str):
        return await self.find_notes(f"deck:\"{deck}\"")

    async def change_deck(self, cards, deck):
        """Moves the given cards to a different deck, creating the deck if it doesn’t exist.

        :param cards: A list of card IDs to move.
        :param deck: The name of the deck to move the cards to.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(cards, list) or not all(isinstance(card, int) for card in cards):
            raise ValueError("Argument 'cards' must be a list of integers.")

        if not isinstance(deck, str):
            raise ValueError("Argument 'deck' must be a string.")

        result = await self.invoke("changeDeck", cards=cards, deck=deck)

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'changeDeck' must be null.")

        return result

    async def delete_decks(self, decks, cards_too):
        """Deletes the given decks, optionally deleting their cards as well.

        :param decks: A list of deck names to delete.
        :param cards_too: A boolean indicating whether to delete the cards in the decks as well.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(decks, list) or not all(isinstance(deck, str) for deck in decks):
            raise ValueError("Argument 'decks' must be a list of strings.")

        if not isinstance(cards_too, bool):
            raise ValueError("Argument 'cards_too' must be a boolean.")

        result = await self.invoke("deleteDecks", decks=decks, cardsToo=cards_too)

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'deleteDecks' must be null.")

        return result

    async def get_deck_config(self, deck):
        """Gets the configuration group object for the given deck.

        :param deck: The name of the deck to retrieve the configuration for.
        :return: A dictionary containing the deck configuration.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(deck, str):
            raise ValueError("Argument 'deck' must be a string.")

        result = await self.invoke("getDeckConfig", deck=deck)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, dict):
            raise AnkiAPIUnexpectedResponse("API response for 'getDeckConfig' must be a dictionary.")

        return result

    async def save_deck_config(self, config):
        """Saves the given configuration group.

        :param config: A dictionary containing the configuration group to save.
        :return: True on success, False if the configuration ID is invalid.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(config, dict):
            raise ValueError("Argument 'config' must be a dictionary.")

        result = await self.invoke("saveDeckConfig", config=config)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'saveDeckConfig' must be a boolean.")

        return result


    async def set_deck_config_id(self, decks, config_id):
        """Changes the configuration group for the given decks to the specified ID.

        :param decks: A list of deck names to update.
        :param config_id: The ID of the configuration group to apply.
        :return: True on success, False otherwise.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(decks, list) or not all(isinstance(deck, str) for deck in decks):
            raise ValueError("Argument 'decks' must be a list of strings.")

        if not isinstance(config_id, int):
            raise ValueError("Argument 'config_id' must be an integer.")

        result = await self.invoke("setDeckConfigId", decks=decks, configId=config_id)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'setDeckConfigId' must be a boolean.")

        return result

    async def clone_deck_config_id(self, name, clone_from=None):
        """Creates a new configuration group with the given name, cloning from an existing group.

        :param name: The name of the new configuration group.
        :param clone_from: The ID of the configuration group to clone from (optional).
        :return: The ID of the new configuration group, or False if the specified group does not exist.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(name, str):
            raise ValueError("Argument 'name' must be a string.")

        if clone_from is not None and not isinstance(clone_from, int):
            raise ValueError("Argument 'clone_from' must be an integer if specified.")

        result = await self.invoke("cloneDeckConfigId", name=name, cloneFrom=clone_from)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, (int, bool)):
            raise AnkiAPIUnexpectedResponse("API response for 'cloneDeckConfigId' must be an integer or a boolean.")

        return result

    async def remove_deck_config_id(self, config_id):
        """Removes the configuration group with the given ID.

        :param config_id: The ID of the configuration group to remove.
        :return: True if successful, False otherwise.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(config_id, int):
            raise ValueError("Argument 'config_id' must be an integer.")

        result = await self.invoke("removeDeckConfigId", configId=config_id)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'removeDeckConfigId' must be a boolean.")

        return result

    async def get_deck_stats(self, decks):
        """Gets statistics such as total cards and cards due for the given decks.

        :param decks: A list of deck names to retrieve statistics for.
        :return: A dictionary with deck IDs as keys and statistics as values.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(decks, list) or not all(isinstance(deck, str) for deck in decks):
            raise ValueError("Argument 'decks' must be a list of strings.")

        result = await self.invoke("getDeckStats", decks=decks)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, dict) or not all(
            isinstance(deck_id, str) and isinstance(stats, dict) and
            "deck_id" in stats and "name" in stats and "new_count" in stats and
            "learn_count" in stats and "review_count" in stats and "total_in_deck" in stats
            for deck_id, stats in result.items()
        ):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'getDeckStats' must be a dictionary with valid statistics for each deck."
            )

        return result

    async def gui_browse(self, query, reorder_cards: Reordering = None):
        """Invokes the Card Browser dialog and searches for a given query.

        :param query: The search query string.
        :param reorder_cards: Determines how the cards should be ordered in the search results.
        :return: A list of card identifiers that match the query.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(query, str):
            raise ValueError("Argument 'query' must be a string.")

        reorder_cards = Reordering.schema().dump(reorder_cards if reorder_cards is not None else {})

        if reorder_cards is not None:
            if not isinstance(reorder_cards, dict) or not all(
                key in reorder_cards for key in ["order", "columnId"]
            ) or not isinstance(reorder_cards["order"], str) or not isinstance(reorder_cards["columnId"], str):
                raise ValueError(
                    "Argument 'reorder_cards' must be a dictionary with 'order' and 'columnId' as strings."
                )

        result = await self.invoke("guiBrowse", query=query, reorderCards=reorder_cards)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(card_id, int) for card_id in result):
            raise AnkiAPIUnexpectedResponse("API response for 'guiBrowse' must be a list of integers.")

        return result

    async def gui_select_card(self, card):
        """Finds the open instance of the Card Browser dialog and selects a note.

        :param card: The card identifier to select.
        :return: True if the Card Browser is open, False otherwise.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(card, int):
            raise ValueError("Argument 'note' must be an integer.")

        result = await self.invoke("guiSelectCard", card=card)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'guiSelectNote' must be a boolean.")

        return result

    async def gui_selected_notes(self):
        """Finds the open instance of the Card Browser dialog and returns selected note identifiers.

        :return: A list of note identifiers that are currently selected.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = await self.invoke("guiSelectedNotes")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(note_id, int) for note_id in result):
            raise AnkiAPIUnexpectedResponse("API response for 'guiSelectedNotes' must be a list of integers.")

        return result

    async def gui_add_card(self, note: Note):
        return await self.add_note(note, True)

    async def gui_edit_note(self, note):
        """Opens the Edit dialog for a note corresponding to the given note ID.

        :param note: The ID of the note to edit.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(note, int):
            raise ValueError("Argument 'note' must be an integer.")

        result = await self.invoke("guiEditNote", note=note)

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'guiEditNote' must be null.")

        return result

    async def gui_current_card(self):
        """Returns information about the current card or null if not in review mode.

        :return: A dictionary containing the current card information, or None if not in review mode.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = await self.invoke("guiCurrentCard")

        if isinstance(result, DeferredResult):
            return result

        if result is not None and not isinstance(result, dict):
            raise AnkiAPIUnexpectedResponse("API response for 'guiCurrentCard' must be a dictionary or null.")

        return result

    async def gui_start_card_timer(self):
        """Starts or resets the timer for the current card.

        :return: True if the timer was started or reset successfully, False otherwise.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = await self.invoke("guiStartCardTimer")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'guiStartCardTimer' must be a boolean.")

        return result

    async def gui_show_question(self):
        """Shows the question text for the current card.

        :return: True if in review mode, False otherwise.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = await self.invoke("guiShowQuestion")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'guiShowQuestion' must be a boolean.")

        return result

    async def gui_show_answer(self):
        """Shows the answer text for the current card.

        :return: True if in review mode, False otherwise.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = await self.invoke("guiShowAnswer")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'guiShowAnswer' must be a boolean.")

        return result

    async def gui_answer_card(self, ease):
        """Answers the current card.

        :param ease: An integer representing the ease level (1: Again, 2: Hard, 3: Good, 4: Easy).
        :return: True if the card was answered successfully, False otherwise.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(ease, int) or not (1 <= ease <= 4):
            raise ValueError("Argument 'ease' must be an integer between 1 and 4.")

        result = await self.invoke("guiAnswerCard", ease=ease)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'guiAnswerCard' must be a boolean.")

        return result

    async def gui_undo(self):
        """Undoes the last action or card.

        :return: True if the undo operation succeeded, False otherwise.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = await self.invoke("guiUndo")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'guiUndo' must be a boolean.")

        return result

    async def gui_deck_overview(self, name):
        """Opens the Deck Overview dialog for the specified deck.

        :param name: The name of the deck.
        :return: True if the operation succeeded, False otherwise.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(name, str):
            raise ValueError("Argument 'name' must be a string.")

        result = await self.invoke("guiDeckOverview", name=name)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'guiDeckOverview' must be a boolean.")

        return result

    async def gui_deck_browser(self):
        """Opens the Deck Browser dialog.

        :return: None
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = await self.invoke("guiDeckBrowser")

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'guiDeckBrowser' must be null.")

        return result

    async def gui_deck_review(self, name):
        """Starts review for the specified deck.

        :param name: The name of the deck.
        :return: True if the operation succeeded, False otherwise.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(name, str):
            raise ValueError("Argument 'name' must be a string.")

        result = await self.invoke("guiDeckReview", name=name)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'guiDeckReview' must be a boolean.")

        return result

    async def gui_import_file(self, path=None):
        """Invokes the Import dialog with an optional file path.

        :param path: The file path to import (optional).
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if path is not None and not isinstance(path, str):
            raise ValueError("Argument 'path' must be a string if provided.")

        result = await self.invoke("guiImportFile", path=path)

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'guiImportFile' must be null.")

        return result

    async def gui_exit_anki(self):
        """Schedules a request to gracefully close Anki.

        :return: None
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = await self.invoke("guiExitAnki")

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'guiExitAnki' must be null.")

        return result

    async def gui_check_database(self):
        """Requests a database check.

        :return: True, as this action always returns true regardless of errors during the check.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = await self.invoke("guiCheckDatabase")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'guiCheckDatabase' must be a boolean.")

        return result

    async def store_media_file(self, filename, data=None, path=None, url=None, delete_existing=True):
        """Stores a file in the media folder with the specified content, path, or URL.

        :param filename: The name of the file to store.
        :param data: Base64-encoded contents of the file (optional).
        :param path: Absolute file path to the content (optional).
        :param url: URL to download the file from (optional).
        :param delete_existing: Whether to delete an existing file with the same name (default: True).
        :return: The name of the stored file.
        :raises ValueError: If the input data type is incorrect or more than one data source is provided.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(filename, str):
            raise ValueError("Argument 'filename' must be a string.")

        if data is not None and not isinstance(data, str):
            raise ValueError("Argument 'data' must be a base64-encoded string if provided.")

        if path is not None and not isinstance(path, str):
            raise ValueError("Argument 'path' must be a string if provided.")

        if url is not None and not isinstance(url, str):
            raise ValueError("Argument 'url' must be a string if provided.")

        if not isinstance(delete_existing, bool):
            raise ValueError("Argument 'delete_existing' must be a boolean.")

        provided_sources = [data, path, url]
        if sum(source is not None for source in provided_sources) != 1:
            raise ValueError("Exactly one of 'data', 'path', or 'url' must be provided.")

        params = {
            "filename": filename,
            "data": data,
            "path": path,
            "url": url,
            "deleteExisting": delete_existing
        }

        # Remove keys with None values to avoid sending unnecessary parameters
        params = {key: value for key, value in params.items() if value is not None}

        result = await self.invoke("storeMediaFile", **params)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, str):
            raise AnkiAPIUnexpectedResponse("API response for 'storeMediaFile' must be a string.")

        return result

    async def retrieve_media_file(self, filename):
        """Retrieves the base64-encoded contents of the specified file.

        :param filename: The name of the file to retrieve.
        :return: The base64-encoded contents of the file, or False if the file does not exist.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(filename, str):
            raise ValueError("Argument 'filename' must be a string.")

        result = await self.invoke("retrieveMediaFile", filename=filename)

        if isinstance(result, DeferredResult):
            return result

        if not (isinstance(result, str) or result is False):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'retrieveMediaFile' must be a base64-encoded string or False."
            )

        return result

    async def get_media_files_names(self, pattern):
        """Gets the names of media files matching the specified pattern.

        :param pattern: The pattern to match filenames (optional).
        :return: A list of media file names matching the pattern.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if pattern is not None and not isinstance(pattern, str):
            raise ValueError("Argument 'pattern' must be a string if provided.")

        result = await self.invoke("getMediaFilesNames", pattern=pattern)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(name, str) for name in result):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'getMediaFilesNames' must be a list of strings."
            )

        return result

    async def get_media_dir_path(self):
        """Gets the full path to the collection.media folder of the currently opened profile.

        :return: The full path to the media directory.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = await self.invoke("getMediaDirPath")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, str):
            raise AnkiAPIUnexpectedResponse("API response for 'getMediaDirPath' must be a string.")

        return result

    async def delete_media_file(self, filename):
        """Deletes the specified file inside the media folder.

        :param filename: The name of the file to delete.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(filename, str):
            raise ValueError("Argument 'filename' must be a string.")

        result = await self.invoke("deleteMediaFile", filename=filename)

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'deleteMediaFile' must be null.")

        return result

    async def request_permission(self):
        """Requests permission to use the API exposed by this plugin.

        :return: A dictionary containing the permission status and additional information if permission is granted.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = await self.invoke("requestPermission")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, dict) or "permission" not in result:
            raise AnkiAPIUnexpectedResponse(
                "API response for 'requestPermission' must be a dictionary containing the 'permission' field."
            )

        return result

    async def version(self):
        """Gets the version of the API exposed by this plugin.

        :return: The API version as an integer.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = await self.invoke("version")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, int):
            raise AnkiAPIUnexpectedResponse("API response for 'version' must be an integer.")

        return result

    async def api_reflect(self, scopes=None, actions=None):
        """Gets information about the AnkiConnect APIs available.

        :param scopes: An optional list of scopes to get reflection information about.
        :param actions: An optional list of API method names to check for.
        :return: A dictionary containing reflection information about the available APIs.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if scopes is not None and not isinstance(scopes, list):
            raise ValueError("Argument 'scopes' must be a list if provided.")

        if actions is not None and not isinstance(actions, list):
            raise ValueError("Argument 'actions' must be a list if provided.")

        result = await self.invoke("apiReflect", scopes=scopes, actions=actions)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, dict) or "scopes" not in result:
            raise AnkiAPIUnexpectedResponse(
                "API response for 'apiReflect' must be a dictionary containing the 'scopes' field."
            )

        return result

    async def sync(self):
        """Synchronizes the local Anki collection with AnkiWeb.

        :return: None
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = await self.invoke("sync")

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'sync' must be null.")

        return result

    async def get_profiles(self):
        """Retrieves the list of profiles.

        :return: A list of profile names.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = await self.invoke("getProfiles")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(profile, str) for profile in result):
            raise AnkiAPIUnexpectedResponse("API response for 'getProfiles' must be a list of strings.")

        return result

    async def get_active_profile(self):
        """Retrieves the active profile.

        :return: The name of the active profile.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = await self.invoke("getActiveProfile")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, str):
            raise AnkiAPIUnexpectedResponse("API response for 'getActiveProfile' must be a string.")

        return result

    async def load_profile(self, name):
        """Selects the specified profile.

        :param name: The name of the profile to load.
        :return: True if the profile was successfully loaded, False otherwise.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(name, str):
            raise ValueError("Argument 'name' must be a string.")

        result = await self.invoke("loadProfile", name=name)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'loadProfile' must be a boolean.")

        return result

    async def export_package(self, deck, path, include_sched=False):
        """Exports a given deck in .apkg format.

        :param deck: The name of the deck to export.
        :param path: The file path to save the .apkg file.
        :param include_sched: Whether to include the cards' scheduling data (default: False).
        :return: True if the export was successful, False otherwise.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(deck, str):
            raise ValueError("Argument 'deck' must be a string.")

        if not isinstance(path, str):
            raise ValueError("Argument 'path' must be a string.")

        if not isinstance(include_sched, bool):
            raise ValueError("Argument 'include_sched' must be a boolean.")

        result = await self.invoke("exportPackage", deck=deck, path=path, includeSched=include_sched)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'exportPackage' must be a boolean.")

        return result

    async def import_package(self, path):
        """Imports a .apkg file into the collection.

        :param path: The file path to the .apkg file (relative to Anki's collection.media folder).
        :return: True if the import was successful, False otherwise.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(path, str):
            raise ValueError("Argument 'path' must be a string.")

        result = await self.invoke("importPackage", path=path)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'importPackage' must be a boolean.")

        return result

    async def reload_collection(self):
        """Tells Anki to reload all data from the database.

        :return: None
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = await self.invoke("reloadCollection")

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'reloadCollection' must be null.")

        return result

    async def model_names(self):
        """Gets the complete list of model names for the current user.

        :return: A list of model names.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = await self.invoke("modelNames")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(name, str) for name in result):
            raise AnkiAPIUnexpectedResponse("API response for 'modelNames' must be a list of strings.")

        return result

    async def model_names_and_ids(self):
        """Gets the complete list of model names and their corresponding IDs for the current user.

        :return: A dictionary with model names as keys and their IDs as values.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = await self.invoke("modelNamesAndIds")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, dict) or not all(
            isinstance(name, str) and isinstance(model_id, int) for name, model_id in result.items()
        ):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'modelNamesAndIds' must be a dictionary with strings as keys and integers as values."
            )

        return result

    async def find_models_by_id(self, model_ids):
        """Gets a list of models for the provided model IDs from the current user.

        :param model_ids: A list of model IDs to retrieve.
        :return: A list of dictionaries containing model details.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_ids, list) or not all(isinstance(model_id, int) for model_id in model_ids):
            raise ValueError("Argument 'model_ids' must be a list of integers.")

        result = await self.invoke("findModelsById", modelIds=model_ids)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(model, dict) for model in result):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'findModelsById' must be a list of dictionaries."
            )

        return result

    async def find_models_by_name(self, model_names):
        """Gets a list of models for the provided model names from the current user.

        :param model_names: A list of model names to retrieve.
        :return: A list of dictionaries containing model details.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_names, list) or not all(isinstance(name, str) for name in model_names):
            raise ValueError("Argument 'model_names' must be a list of strings.")

        result = await self.invoke("findModelsByName", modelNames=model_names)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(model, dict) for model in result):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'findModelsByName' must be a list of dictionaries."
            )

        return result

    async def model_field_names(self, model_name):
        """Gets the complete list of field names for the provided model name.

        :param model_name: The name of the model to retrieve field names for.
        :return: A list of field names.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_name, str):
            raise ValueError("Argument 'model_name' must be a string.")

        result = await self.invoke("modelFieldNames", modelName=model_name)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(field_name, str) for field_name in result):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'modelFieldNames' must be a list of strings."
            )

        return result

    async def model_field_descriptions(self, model_name):
        """Gets the complete list of field descriptions for the provided model name.

        :param model_name: The name of the model to retrieve field descriptions for.
        :return: A list of field descriptions.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_name, str):
            raise ValueError("Argument 'model_name' must be a string.")

        result = await self.invoke("modelFieldDescriptions", modelName=model_name)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(description, str) for description in result):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'modelFieldDescriptions' must be a list of strings."
            )

        return result

    async def model_field_fonts(self, model_name):
        """Gets the complete list of fonts along with their font sizes for the specified model.

        :param model_name: The name of the model to retrieve font details for.
        :return: A dictionary with field names as keys and font details as values.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_name, str):
            raise ValueError("Argument 'model_name' must be a string.")

        result = await self.invoke("modelFieldFonts", modelName=model_name)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, dict) or not all(
            isinstance(field, str) and isinstance(details, dict) and "font" in details and "size" in details and
            isinstance(details["font"], str) and isinstance(details["size"], int)
            for field, details in result.items()
        ):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'modelFieldFonts' must be a dictionary with valid font details."
            )

        return result

    async def model_fields_on_templates(self, model_name):
        """Returns the fields on the question and answer sides of each card template for the specified model.

        :param model_name: The name of the model to retrieve fields on templates for.
        :return: A dictionary with template names as keys and lists of fields as values.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_name, str):
            raise ValueError("Argument 'model_name' must be a string.")

        result = await self.invoke("modelFieldsOnTemplates", modelName=model_name)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, dict) or not all(
            isinstance(template, str) and isinstance(fields, list) and
            len(fields) == 2 and all(isinstance(field_list, list) and all(isinstance(field, str) for field in field_list) for field_list in fields)
            for template, fields in result.items()
        ):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'modelFieldsOnTemplates' must be a dictionary with valid template field details."
            )

        return result

    async def create_model(self, model_name, in_order_fields, card_templates, css=None, is_cloze=False):
        """Creates a new model to be used in Anki.

        :param model_name: The name of the new model.
        :param in_order_fields: A list of field names in the order they should appear.
        :param card_templates: A list of dictionaries defining card templates.
        :param css: Optional CSS for the model (default: Anki's built-in CSS).
        :param is_cloze: Whether the model should be created as Cloze (default: False).
        :return: A dictionary containing the created model details.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_name, str):
            raise ValueError("Argument 'model_name' must be a string.")

        if not isinstance(in_order_fields, list) or not all(isinstance(field, str) for field in in_order_fields):
            raise ValueError("Argument 'in_order_fields' must be a list of strings.")

        if not isinstance(card_templates, list) or not all(
            isinstance(template, dict) and "Front" in template and "Back" in template
            for template in card_templates
        ):
            raise ValueError(
                "Argument 'card_templates' must be a list of dictionaries with 'Front' and 'Back' keys."
            )

        if css is not None and not isinstance(css, str):
            raise ValueError("Argument 'css' must be a string if provided.")

        if not isinstance(is_cloze, bool):
            raise ValueError("Argument 'is_cloze' must be a boolean.")

        result = await self.invoke(
            "createModel",
            modelName=model_name,
            inOrderFields=in_order_fields,
            css=css,
            isCloze=is_cloze,
            cardTemplates=card_templates
        )

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, dict):
            raise AnkiAPIUnexpectedResponse("API response for 'createModel' must be a dictionary.")

        return result

    async def model_templates(self, model_name):
        """Gets the template content for each card connected to the provided model by name.

        :param model_name: The name of the model to retrieve templates for.
        :return: A dictionary with card names as keys and template content as values.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_name, str):
            raise ValueError("Argument 'model_name' must be a string.")

        result = await self.invoke("modelTemplates", modelName=model_name)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, dict) or not all(
            isinstance(card, str) and isinstance(content, dict) and "Front" in content and "Back" in content
            for card, content in result.items()
        ):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'modelTemplates' must be a dictionary with valid card template content."
            )

        return result

    async def model_styling(self, model_name):
        """Gets the CSS styling for the provided model by name.

        :param model_name: The name of the model to retrieve styling for.
        :return: A dictionary containing the CSS styling.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_name, str):
            raise ValueError("Argument 'model_name' must be a string.")

        result = await self.invoke("modelStyling", modelName=model_name)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, dict) or "css" not in result or not isinstance(result["css"], str):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'modelStyling' must be a dictionary containing the 'css' field."
            )

        return result

    async def update_model_templates(self, model_name, templates):
        """Modifies the templates of an existing model by name.

        :param model_name: The name of the model to update.
        :param templates: A dictionary specifying the templates to modify.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_name, str):
            raise ValueError("Argument 'model_name' must be a string.")

        if not isinstance(templates, dict) or not all(
            isinstance(card, str) and isinstance(content, dict) and "Front" in content and "Back" in content
            for card, content in templates.items()
        ):
            raise ValueError(
                "Argument 'templates' must be a dictionary with card names as keys and dictionaries containing 'Front' and 'Back' keys as values."
            )

        result = await self.invoke("updateModelTemplates", model={"name": model_name, "templates": templates})

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'updateModelTemplates' must be null.")

        return result

    async def update_model_styling(self, model_name, css):
        """Modifies the CSS styling of an existing model by name.

        :param model_name: The name of the model to update.
        :param css: The CSS styling to apply to the model.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_name, str):
            raise ValueError("Argument 'model_name' must be a string.")

        if not isinstance(css, str):
            raise ValueError("Argument 'css' must be a string.")

        result = await self.invoke("updateModelStyling", model={"name": model_name, "css": css})

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'updateModelStyling' must be null.")

        return result

    async def find_and_replace_in_models(self, model_name, find_text, replace_text, front=False, back=False, css=False):
        """Finds and replaces a string in an existing model by model name.

        :param model_name: The name of the model.
        :param find_text: The text to find.
        :param replace_text: The text to replace with.
        :param front: Whether to replace in the front template (default: False).
        :param back: Whether to replace in the back template (default: False).
        :param css: Whether to replace in the CSS (default: False).
        :return: The number of replacements made.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_name, str):
            raise ValueError("Argument 'model_name' must be a string.")

        if not isinstance(find_text, str):
            raise ValueError("Argument 'find_text' must be a string.")

        if not isinstance(replace_text, str):
            raise ValueError("Argument 'replace_text' must be a string.")

        if not all(isinstance(flag, bool) for flag in [front, back, css]):
            raise ValueError("Arguments 'front', 'back', and 'css' must be booleans.")

        result = await self.invoke(
            "findAndReplaceInModels",
            model={
                "modelName": model_name,
                "findText": find_text,
                "replaceText": replace_text,
                "front": front,
                "back": back,
                "css": css,
            },
        )

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, int):
            raise AnkiAPIUnexpectedResponse("API response for 'findAndReplaceInModels' must be an integer.")

        return result

    async def model_template_rename(self, model_name, old_template_name, new_template_name):
        """Renames a template in an existing model.

        :param model_name: The name of the model.
        :param old_template_name: The current name of the template.
        :param new_template_name: The new name for the template.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_name, str):
            raise ValueError("Argument 'model_name' must be a string.")

        if not isinstance(old_template_name, str):
            raise ValueError("Argument 'old_template_name' must be a string.")

        if not isinstance(new_template_name, str):
            raise ValueError("Argument 'new_template_name' must be a string.")

        result = await self.invoke(
            "modelTemplateRename",
            modelName=model_name,
            oldTemplateName=old_template_name,
            newTemplateName=new_template_name,
        )

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'modelTemplateRename' must be null.")

        return result

    async def model_template_reposition(self, model_name, template_name, index):
        """Repositions a template in an existing model.

        :param model_name: The name of the model.
        :param template_name: The name of the template to reposition.
        :param index: The new index position for the template (starting at 0).
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_name, str):
            raise ValueError("Argument 'model_name' must be a string.")

        if not isinstance(template_name, str):
            raise ValueError("Argument 'template_name' must be a string.")

        if not isinstance(index, int):
            raise ValueError("Argument 'index' must be an integer.")

        result = await self.invoke(
            "modelTemplateReposition",
            modelName=model_name,
            templateName=template_name,
            index=index,
        )

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'modelTemplateReposition' must be null.")

        return result

    async def model_template_add(self, model_name, template):
        """Adds a template to an existing model by name.

        :param model_name: The name of the model.
        :param template: A dictionary defining the template to add (must include 'Name', 'Front', and 'Back').
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_name, str):
            raise ValueError("Argument 'model_name' must be a string.")

        if not isinstance(template, dict) or not all(
            key in template for key in ["Name", "Front", "Back"]
        ):
            raise ValueError(
                "Argument 'template' must be a dictionary containing 'Name', 'Front', and 'Back'."
            )

        result = await self.invoke("modelTemplateAdd", modelName=model_name, template=template)

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'modelTemplateAdd' must be null.")

        return result

    async def model_template_remove(self, model_name, template_name):
        """Removes a template from an existing model.

        :param model_name: The name of the model.
        :param template_name: The name of the template to remove.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_name, str):
            raise ValueError("Argument 'model_name' must be a string.")

        if not isinstance(template_name, str):
            raise ValueError("Argument 'template_name' must be a string.")

        result = await self.invoke(
            "modelTemplateRemove",
            modelName=model_name,
            templateName=template_name,
        )

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'modelTemplateRemove' must be null.")

        return result
    async def model_field_rename(self, model_name, old_field_name, new_field_name):
        """Renames the field name of a given model.

        :param model_name: The name of the model.
        :param old_field_name: The current name of the field.
        :param new_field_name: The new name for the field.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not all(isinstance(arg, str) for arg in [model_name, old_field_name, new_field_name]):
            raise ValueError("Arguments 'model_name', 'old_field_name', and 'new_field_name' must be strings.")

        result = await self.invoke(
            "modelFieldRename",
            modelName=model_name,
            oldFieldName=old_field_name,
            newFieldName=new_field_name,
        )

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'modelFieldRename' must be null.")

        return result

    async def model_field_reposition(self, model_name, field_name, index):
        """Repositions the field within the field list of a given model.

        :param model_name: The name of the model.
        :param field_name: The name of the field to reposition.
        :param index: The new index position for the field (starting at 0).
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not all(isinstance(arg, str) for arg in [model_name, field_name]):
            raise ValueError("Arguments 'model_name' and 'field_name' must be strings.")

        if not isinstance(index, int):
            raise ValueError("Argument 'index' must be an integer.")

        result = await self.invoke(
            "modelFieldReposition",
            modelName=model_name,
            fieldName=field_name,
            index=index,
        )

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'modelFieldReposition' must be null.")

        return result

    async def model_field_add(self, model_name, field_name, index=None):
        """Creates a new field within a given model.

        :param model_name: The name of the model.
        :param field_name: The name of the new field.
        :param index: Optional index value for positioning the field (default: added to the end).
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not all(isinstance(arg, str) for arg in [model_name, field_name]):
            raise ValueError("Arguments 'model_name' and 'field_name' must be strings.")

        if index is not None and not isinstance(index, int):
            raise ValueError("Argument 'index' must be an integer if provided.")

        params = {"modelName": model_name, "fieldName": field_name}
        if index is not None:
            params["index"] = index

        result = await self.invoke("modelFieldAdd", **params)

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'modelFieldAdd' must be null.")

        return result

    async def model_field_remove(self, model_name, field_name):
        """Deletes a field within a given model.

        :param model_name: The name of the model.
        :param field_name: The name of the field to remove.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not all(isinstance(arg, str) for arg in [model_name, field_name]):
            raise ValueError("Arguments 'model_name' and 'field_name' must be strings.")

        result = await self.invoke(
            "modelFieldRemove",
            modelName=model_name,
            fieldName=field_name,
        )

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'modelFieldRemove' must be null.")

        return result

    async def model_field_set_font(self, model_name, field_name, font):
        """Sets the font for a field within a given model.

        :param model_name: The name of the model.
        :param field_name: The name of the field.
        :param font: The font to set for the field.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not all(isinstance(arg, str) for arg in [model_name, field_name, font]):
            raise ValueError("Arguments 'model_name', 'field_name', and 'font' must be strings.")

        result = await self.invoke(
            "modelFieldSetFont",
            modelName=model_name,
            fieldName=field_name,
            font=font,
        )

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'modelFieldSetFont' must be null.")

        return result

    async def model_field_set_font_size(self, model_name, field_name, font_size):
        """Sets the font size for a field within a given model.

        :param model_name: The name of the model.
        :param field_name: The name of the field.
        :param font_size: The font size to set for the field.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_name, str):
            raise ValueError("Argument 'model_name' must be a string.")

        if not isinstance(field_name, str):
            raise ValueError("Argument 'field_name' must be a string.")

        if not isinstance(font_size, int):
            raise ValueError("Argument 'font_size' must be an integer.")

        result = await self.invoke(
            "modelFieldSetFontSize",
            modelName=model_name,
            fieldName=field_name,
            fontSize=font_size,
        )

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'modelFieldSetFontSize' must be null.")

        return result

    async def model_field_set_description(self, model_name, field_name, description):
        """Sets the description for a field within a given model.

        :param model_name: The name of the model.
        :param field_name: The name of the field.
        :param description: The description to set for the field.
        :return: True if successful, False otherwise.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not all(isinstance(arg, str) for arg in [model_name, field_name, description]):
            raise ValueError("Arguments 'model_name', 'field_name', and 'description' must be strings.")

        result = await self.invoke(
            "modelFieldSetDescription",
            modelName=model_name,
            fieldName=field_name,
            description=description,
        )

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'modelFieldSetDescription' must be a boolean.")

        return result

    async def update_note_tags(self, note_id, tags):
        """Set a note's tags by note ID. Old tags will be removed.

        :param note_id: The ID of the note to update.
        :param tags: A list of tags to set for the note.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(note_id, int):
            raise ValueError("Argument 'note_id' must be an integer.")

        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise ValueError("Argument 'tags' must be a list of strings.")

        result = await self.invoke("updateNoteTags", note=note_id, tags=tags)

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'updateNoteTags' must be null.")

        return result

    async def get_note_tags(self, note_id):
        """Get a note's tags by note ID.

        :param note_id: The ID of the note to retrieve tags for.
        :return: A list of tags associated with the note.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(note_id, int):
            raise ValueError("Argument 'note_id' must be an integer.")

        result = await self.invoke("getNoteTags", note=note_id)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(tag, str) for tag in result):
            raise AnkiAPIUnexpectedResponse("API response for 'getNoteTags' must be a list of strings.")

        return result

    async def add_tags(self, note_ids, tags):
        """Adds tags to notes by note ID.

        :param note_ids: A list of note IDs to add tags to.
        :param tags: A string of tags to add, separated by spaces.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(note_ids, list) or not all(isinstance(note_id, int) for note_id in note_ids):
            raise ValueError("Argument 'note_ids' must be a list of integers.")

        if not isinstance(tags, str):
            raise ValueError("Argument 'tags' must be a string.")

        result = await self.invoke("addTags", notes=note_ids, tags=tags)

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'addTags' must be null.")

        return result

    async def remove_tags(self, note_ids, tags):
        """Removes tags from notes by note ID.

        :param note_ids: A list of note IDs to remove tags from.
        :param tags: A string of tags to remove, separated by spaces.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(note_ids, list) or not all(isinstance(note_id, int) for note_id in note_ids):
            raise ValueError("Argument 'note_ids' must be a list of integers.")

        if not isinstance(tags, str):
            raise ValueError("Argument 'tags' must be a string.")

        result = await self.invoke("removeTags", notes=note_ids, tags=tags)

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'removeTags' must be null.")

        return result

    async def get_tags(self):
        """Gets the complete list of tags for the current user.

        :return: A list of tags.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = await self.invoke("getTags")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(tag, str) for tag in result):
            raise AnkiAPIUnexpectedResponse("API response for 'getTags' must be a list of strings.")

        return result

    async def clear_unused_tags(self):
        """Clears all the unused tags in the notes for the current user.

        :return: None
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = await self.invoke("clearUnusedTags")

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'clearUnusedTags' must be null.")

        return result

    async def replace_tags(self, notes, tag_to_replace, replace_with_tag):
        """Replaces tags in notes by note ID.

        :param notes: A list of note IDs to replace tags in.
        :param tag_to_replace: The tag to replace.
        :param replace_with_tag: The tag to replace with.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(notes, list) or not all(isinstance(note, int) for note in notes):
            raise ValueError("Argument 'notes' must be a list of integers.")

        if not isinstance(tag_to_replace, str):
            raise ValueError("Argument 'tag_to_replace' must be a string.")

        if not isinstance(replace_with_tag, str):
            raise ValueError("Argument 'replace_with_tag' must be a string.")

        result = await self.invoke(
            "replaceTags",
            notes=notes,
            tag_to_replace=tag_to_replace,
            replace_with_tag=replace_with_tag,
        )

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'replaceTags' must be null.")

        return result

    async def replace_tags_in_all_notes(self, tag_to_replace, replace_with_tag):
        """Replaces tags in all notes for the current user.

        :param tag_to_replace: The tag to replace.
        :param replace_with_tag: The tag to replace with.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(tag_to_replace, str):
            raise ValueError("Argument 'tag_to_replace' must be a string.")

        if not isinstance(replace_with_tag, str):
            raise ValueError("Argument 'replace_with_tag' must be a string.")

        result = await self.invoke(
            "replaceTagsInAllNotes",
            tag_to_replace=tag_to_replace,
            replace_with_tag=replace_with_tag,
        )

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'replaceTagsInAllNotes' must be null.")

        return result

    async def find_notes(self, query):
        """Returns an array of note IDs for a given query.

        :param query: The search query string.
        :return: A list of note IDs matching the query.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(query, str):
            raise ValueError("Argument 'query' must be a string.")

        result = await self.invoke("findNotes", query=query)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(note_id, int) for note_id in result):
            raise AnkiAPIUnexpectedResponse("API response for 'findNotes' must be a list of integers.")

        return result

    async def notes_info(self, note_ids):
        """Returns a list of objects containing detailed information for each note ID.

        :param note_ids: A list of note IDs to retrieve information for.
        :return: A list of dictionaries containing note details.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(note_ids, list) or not all(isinstance(note_id, int) for note_id in note_ids):
            raise ValueError("Argument 'note_ids' must be a list of integers.")

        result = await self.invoke("notesInfo", notes=note_ids)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(note, dict) for note in result):
            raise AnkiAPIUnexpectedResponse("API response for 'notesInfo' must be a list of dictionaries.")

        return result

    async def notes_mod_time(self, note_ids):
        """Returns a list of objects containing the modification time for each note ID.

        :param note_ids: A list of note IDs to retrieve modification times for.
        :return: A list of dictionaries containing note ID and modification time.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(note_ids, list) or not all(isinstance(note_id, int) for note_id in note_ids):
            raise ValueError("Argument 'note_ids' must be a list of integers.")

        result = await self.invoke("notesModTime", notes=note_ids)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(
            isinstance(note, dict) and "noteId" in note and "mod" in note and
            isinstance(note["noteId"], int) and isinstance(note["mod"], int)
            for note in result
        ):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'notesModTime' must be a list of dictionaries with 'noteId' and 'mod' keys."
            )

        return result

    async def delete_notes(self, note_ids):
        """Deletes notes with the given IDs. All associated cards will also be deleted.

        :param note_ids: A list of note IDs to delete.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(note_ids, list) or not all(isinstance(note_id, int) for note_id in note_ids):
            raise ValueError("Argument 'note_ids' must be a list of integers.")

        result = await self.invoke("deleteNotes", notes=note_ids)

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'deleteNotes' must be null.")

        return result

    async def remove_empty_notes(self):
        """Removes all empty notes for the current user.

        :return: None
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = await self.invoke("removeEmptyNotes")

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'removeEmptyNotes' must be null.")

        return result

    async def get_num_cards_reviewed_today(self):
        """Gets the count of cards that have been reviewed today.

        :return: The number of cards reviewed today.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = await self.invoke("getNumCardsReviewedToday")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, int):
            raise AnkiAPIUnexpectedResponse("API response for 'getNumCardsReviewedToday' must be an integer.")

        return result

    async def get_num_cards_reviewed_by_day(self):
        """Gets the number of cards reviewed as a list of pairs (dateString, number).

        :return: A list of tuples containing date strings and review counts.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = await self.invoke("getNumCardsReviewedByDay")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(
            isinstance(item, list) and len(item) == 2 and isinstance(item[0], str) and isinstance(item[1], int)
            for item in result
        ):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'getNumCardsReviewedByDay' must be a list of [dateString, integer] pairs."
            )

        return result

    async def get_collection_stats_html(self, whole_collection=True):
        """Gets the collection statistics report in HTML format.

        :param whole_collection: Whether to get stats for the whole collection (default: True).
        :return: The HTML report as a string.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(whole_collection, bool):
            raise ValueError("Argument 'whole_collection' must be a boolean.")

        result = await self.invoke("getCollectionStatsHTML", wholeCollection=whole_collection)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, str):
            raise AnkiAPIUnexpectedResponse("API response for 'getCollectionStatsHTML' must be a string.")

        return result

    async def card_reviews(self, deck, start_id):
        """Requests all card reviews for a specified deck after a certain time.

        :param deck: The name of the deck to query.
        :param start_id: The latest Unix time not included in the result.
        :return: A list of 9-tuples with review data.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(deck, str):
            raise ValueError("Argument 'deck' must be a string.")

        if not isinstance(start_id, int):
            raise ValueError("Argument 'start_id' must be an integer.")

        result = await self.invoke("cardReviews", deck=deck, startID=start_id)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(
            isinstance(item, list) and len(item) == 9 and all(isinstance(value, (int, float)) for value in item)
            for item in result
        ):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'cardReviews' must be a list of 9-tuples with numerical values."
            )

        return result

    async def get_reviews_of_cards(self, card_ids):
        """Requests all card reviews for each card ID.

        :param card_ids: A list of card IDs to retrieve reviews for.
        :return: A dictionary mapping each card ID to a list of review dictionaries.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(card_ids, list) or not all(isinstance(card_id, int) for card_id in card_ids):
            raise ValueError("Argument 'card_ids' must be a list of integers.")

        result = await self.invoke("getReviewsOfCards", cards=card_ids)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, dict) or not all(
            isinstance(card_id, str) and isinstance(reviews, list) and all(
                isinstance(review, dict) and all(
                    key in review for key in ["id", "usn", "ease", "ivl", "lastIvl", "factor", "time", "type"]
                ) for review in reviews
            )
            for card_id, reviews in result.items()
        ):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'getReviewsOfCards' must be a dictionary mapping card IDs to lists of review dictionaries."
            )

        return result

    async def get_latest_review_id(self, deck):
        """Returns the unix time of the latest review for the given deck.

        :param deck: The name of the deck to query.
        :return: The Unix time of the latest review, or 0 if no reviews exist.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(deck, str):
            raise ValueError("Argument 'deck' must be a string.")

        result = await self.invoke("getLatestReviewID", deck=deck)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, int):
            raise AnkiAPIUnexpectedResponse("API response for 'getLatestReviewID' must be an integer.")

        return result

    async def insert_reviews(self, reviews):
        """Inserts the given reviews into the database.

        :param reviews: A list of 9-tuples representing review data.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(reviews, list) or not all(
            isinstance(review, (list, tuple)) and len(review) == 9 and all(
                isinstance(value, (int, float)) for value in review
            )
            for review in reviews
        ):
            raise ValueError(
                "Argument 'reviews' must be a list of 9-tuples with numerical values."
            )

        result = await self.invoke("insertReviews", reviews=reviews)

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'insertReviews' must be null.")

        return result

    async def add_notes(self, notes: List[Note]):
        """
        Inserts the given notes into the Anki collection.

        It should be noted that there is a subtle difference between an `addNotes`
        action and a `multi` action composed of many individual `addNote` actions.
        In the latter case, add notes

        :param notes: the notes to add.
        :raises ValueError: If the input data type is incorrect or required fields are missing.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = await self.invoke('addNotes', notes=[note.to_anki_params() for note in notes])

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(item, int) for item in result):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'addNotes' must be a list of cards added."
            )
        return result

    async def can_add_notes(self, notes: List[Note], detailed=False):
        """
        Inserts the given notes into the Anki collection.
        :param notes: the notes to add.
        :param detailed: If True, return a detailed version of the errors when something goes wrong.
        :raises ValueError: If the input data type is incorrect or required fields are missing.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        api_name = "canAddNotesWithErrorDetail" if detailed else "canAddNotes"
        result = await self.invoke(api_name, notes=[note.to_anki_params() for note in notes])

        if isinstance(result, DeferredResult):
            return result

        if result is not None and not isinstance(result, list):
            raise AnkiAPIUnexpectedResponse(f"API response for '{api_name}' must be a list.")
        return result

    async def add_note(self, note: Note, open_gui=False):
        """Creates a note using the given deck and model, with the provided field values and tags.
        :raises ValueError: If the input data type is incorrect or required fields are missing.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        api_name = "guiAddCards" if open_gui else "addNote"
        result = await self.invoke(api_name, note=note.to_anki_params())

        if isinstance(result, DeferredResult):
            return result

        if result is not None and not isinstance(result, int):
            raise AnkiAPIUnexpectedResponse(f"API response for '{api_name}' must be an integer.")
        return result

    # MARK: Constructive Actions

    async def add_vocab_card(self, deck_name: str, front: str, back: str, examples: str, open_gui = False, images: List[Resource] = None, tags: List[str] = None):
        return await self.add_note(
            Note.make_basic_card(deck_name, front, back, examples, images, tags),
            open_gui=open_gui,
        )

    async def gui_add_vocab_card(self, deck_name: str, front: str, back: str, examples: str, images: List[Resource] = None, tags: List[str] = None):
        return await self.add_vocab_card(deck_name=deck_name, front=front, back=back, examples=examples, open_gui=True, images=images, tags=tags)

class Client(BaseClient):
    """A small wrapper around the AnkiConnect API

    The AnkiConnect API ("https://git.sr.ht/~foosoft/anki-connect") runs
    a local HTTP server on port 8765 that allows users to modify and query
    the local Anki database. All actions supported by the Anki GUI are also
    supported by AnkiConnect.

    To interact with AnkiConnect, instantiate an instance of `anki.connect.Client`

    ```python
    from anki.connect import Client
    ac_client = Client()
    card_ids = ac_client.find_cards('deck:*')
    cards_are_due = ac_client.are_due(card_ids)
    ```

    The AnkiConnect API also supports submitting batches of
    commands using the `multi` action. This is supported by creating
    an `anki.BatchManager` instance. You shouldn't need to construct
    one manually: instead, use the `send_batch` and `make_batch` methods:

    ```
    with ac_client.send_batch() as batch:
        ease_factors = batch.get_ease_factors(card_ids)
    ```

    Accessing the client
    """
    def __del__(self):
        if self.sync_on_dtor:
            self.sync()

    @contextmanager
    def send_batch(self):
        old_batcher = self.batcher
        if self.batcher is None:
            self.batcher = BatchManager(self)
        yield self.batcher
        self.batcher.sync_dispatch()
        self.batcher = old_batcher

    def invoke(self, action, **params):
        if self.batcher:
            return self.batcher.add_action(self.version, action, **params)
        else:
            return self.invoke_no_batch(action, **params)

    def invoke_no_batch(self, action, **params):
        request_body = BatchManager.make_request(self.version, action, **params)
        payload = json.dumps(request_body, indent=2)
        if self.log_api_calls:
            log(INFO, 'Request: ')
            log(INFO, payload)
        with httpx.Client() as client:
            try:
                response = client.post(self.anki_url, json=request_body)
                response.raise_for_status()
            except httpx.RequestError as exc:
                raise AnkiAPIException(
                    f"An error occurred while requesting {exc.request.url!r}."
                ) from exc
            except httpx.HTTPStatusError as exc:
                raise AnkiAPIException(
                    f"HTTP error occurred: {exc.response.status_code} {exc.response.text}"
                ) from exc
        response = response.json()
        if self.log_api_calls:
            log(INFO, 'Response: ')
            log(INFO,json.dumps(response, indent=2))
        parsed_response = BatchManager.parse_response(response)
        if isinstance(parsed_response, Exception):
            raise parsed_response
        return parsed_response

    # MARK: Card Actions
    def get_ease_factors(self, cards):
        """Retrieves the ease factors for the given cards.

        :param cards: A list of card IDs for which to retrieve ease factors.
        :return: A list of ease factors in the same order as the provided card IDs.
        :raises ValueError: If the input or output data types are incorrect.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(cards, list) or not all(isinstance(card, int) for card in cards):
            raise ValueError("Argument 'cards' must be a list of integers.")

        result = self.invoke("getEaseFactors", cards=cards)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(factor, (bool, type(None))) for factor in result):
            raise AnkiAPIUnexpectedResponse("API response for 'getEaseFactors' must be a list of integers or None")

        return result

    def set_ease_factors(self, cards, ease_factors):
        """Sets the ease factors for the given cards.

        :param cards: A list of card IDs to update.
        :param ease_factors: A list of ease factors corresponding to the card IDs.
        :return: A list of booleans indicating success for each card.
        :raises ValueError: If the input or output data types are incorrect.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(cards, list) or not all(isinstance(card, int) for card in cards):
            raise ValueError("Argument 'cards' must be a list of integers.")

        if not isinstance(ease_factors, list) or not all(isinstance(factor, int) for factor in ease_factors):
            raise ValueError("Argument 'ease_factors' must be a list of integers.")

        if len(cards) != len(ease_factors):
            raise ValueError("Arguments 'cards' and 'ease_factors' must have the same length.")

        result = self.invoke("setEaseFactors", cards=cards, easeFactors=ease_factors)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(success, bool) for success in result):
            raise AnkiAPIUnexpectedResponse("API response for 'setEaseFactors' must be a list of booleans.")

        return result

    def suspend(self, cards):
        """Suspends the given cards by their IDs.

        :param cards: A list of card IDs to suspend.
        :return: True if at least one card was successfully suspended, otherwise False.
        :raises ValueError: If the input data type is incorrect or the API response is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(cards, list) or not all(isinstance(card, int) for card in cards):
            raise ValueError("Argument 'cards' must be a list of integers.")

        result = self.invoke("suspend", cards=cards)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'suspend' must be a boolean.")

        return result

    def unsuspend(self, cards):
        """Unsuspends the given cards by their IDs.

        :param cards: A list of card IDs to unsuspend.
        :return: True if at least one card was successfully unsuspended, otherwise False.
        :raises ValueError: If the input data type is incorrect or the API response is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(cards, list) or not all(isinstance(card, int) for card in cards):
            raise ValueError("Argument 'cards' must be a list of integers.")

        result = self.invoke("unsuspend", cards=cards)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'unsuspend' must be a boolean.")

        return result

    def suspended(self, card):
        """Checks if a given card is suspended by its ID.

        :param card: The ID of the card to check.
        :return: True if the card is suspended, otherwise False.
        :raises ValueError: If the input data type is incorrect or the API response is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(card, int):
            raise ValueError("Argument 'card' must be an integer.")

        result = self.invoke("suspended", card=card)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'suspended' must be a boolean.")

        return result

    def are_suspended(self, cards):
        """Checks if the given cards are suspended.

        :param cards: A list of card IDs to check.
        :return: A list indicating whether each card is suspended (True, False, or None if card doesn’t exist).
        :raises ValueError: If the input data type is incorrect or the API response is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(cards, list) or not all(isinstance(card, int) for card in cards):
            raise ValueError("Argument 'cards' must be a list of integers.")

        result = self.invoke("areSuspended", cards=cards)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(r, (bool, type(None))) for r in result):
            raise AnkiAPIUnexpectedResponse("API response for 'areSuspended' must be a list of booleans or None values.")

        return result

    def are_due(self, cards):
        """Checks if the given cards are due.

        :param cards: A list of card IDs to check.
        :return: A list indicating whether each card is due (True or False).
        :raises ValueError: If the input data type is incorrect or the API response is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(cards, list) or not all(isinstance(card, int) for card in cards):
            raise ValueError("Argument 'cards' must be a list of integers.")

        result = self.invoke("areDue", cards=cards)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(r, bool) for r in result):
            raise AnkiAPIUnexpectedResponse("API response for 'areDue' must be a list of booleans.")

        return result

    def get_intervals(self, cards, complete=False):
        """Retrieves the intervals for the given cards.

        :param cards: A list of card IDs to check.
        :param complete: If True, returns all intervals for each card; otherwise, only the most recent intervals.
        :return: A list of intervals (in days or seconds) or a 2D list of intervals if complete is True.
        :raises ValueError: If the input data type is incorrect or the API response is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(cards, list) or not all(isinstance(card, int) for card in cards):
            raise ValueError("Argument 'cards' must be a list of integers.")

        if not isinstance(complete, bool):
            raise ValueError("Argument 'complete' must be a boolean.")

        result = self.invoke("getIntervals", cards=cards, complete=complete)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list):
            raise AnkiAPIUnexpectedResponse("API response for 'getIntervals' must be a list.")

        if complete:
            if not all(isinstance(intervals, list) and all(isinstance(i, int) for i in intervals) for intervals in result):
                raise AnkiAPIUnexpectedResponse("API response for 'getIntervals' with complete=True must be a 2D list of integers.")
        else:
            if not all(isinstance(interval, int) for interval in result):
                raise AnkiAPIUnexpectedResponse("API response for 'getIntervals' with complete=False must be a list of integers.")
        return result

    def find_cards(self, query):
        """Finds card IDs based on a given query.

        :param query: The search query string to find cards.
        :return: A list of card IDs matching the query.
        :raises ValueError: If the input data type is incorrect or the API response is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(query, str):
            raise ValueError("Argument 'query' must be a string.")

        result = self.invoke("findCards", query=query)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(card_id, int) for card_id in result):
            raise AnkiAPIUnexpectedResponse("API response for 'findCards' must be a list of integers.")

        return result

    def cards_to_notes(self, cards):
        """Retrieves note IDs for the given card IDs.

        :param cards: A list of card IDs to map to note IDs.
        :return: A list of unique note IDs corresponding to the card IDs.
        :raises ValueError: If the input data type is incorrect or the API response is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(cards, list) or not all(isinstance(card, int) for card in cards):
            raise ValueError("Argument 'cards' must be a list of integers.")

        result = self.invoke("cardsToNotes", cards=cards)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(note_id, int) for note_id in result):
            raise AnkiAPIUnexpectedResponse("API response for 'cardsToNotes' must be a list of integers.")

        return result

    def cards_mod_time(self, cards):
        """Retrieves modification times for the given card IDs.

        :param cards: A list of card IDs to retrieve modification times for.
        :return: A list of dictionaries, each containing a card ID and its modification time.
        :raises ValueError: If the input data type is incorrect or the API response is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(cards, list) or not all(isinstance(card, int) for card in cards):
            raise ValueError("Argument 'cards' must be a list of integers.")

        result = self.invoke("cardsModTime", cards=cards)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(
            not entry or
            ((isinstance(entry, dict) and "cardId" in entry and "mod" in entry) and
            isinstance(entry["cardId"], int) and isinstance(entry["mod"], int)) for entry in result
        ):
            raise AnkiAPIUnexpectedResponse("API response for 'cardsModTime' must be a list of dictionaries with 'cardId' and 'mod' keys.")

        return result

    def cards_info(self, cards: List[int]):
        """Retrieves detailed information for the given card IDs.

        :param cards: A list of card IDs to retrieve information for.
        :return: A list of dictionaries containing detailed information for each card.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(cards, list) or not all(isinstance(card, int) for card in cards):
            raise ValueError("Argument 'cards' must be a list of integers.")

        result = self.invoke("cardsInfo", cards=cards)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list):
            raise AnkiAPIUnexpectedResponse("API response for 'cardsInfo' must be a list of dictionaries.")

        for card_info in result:
            if not card_info:
                continue

            required_keys = {
                "answer", "question", "deckName", "modelName", "fieldOrder", "fields",
                "css", "cardId", "interval", "note", "ord", "type", "queue", "due",
                "reps", "lapses", "left", "mod"
            }

            if not isinstance(card_info, dict) or not required_keys.issubset(card_info.keys()):
                raise AnkiAPIUnexpectedResponse(
                    "Each entry in the API response for 'cardsInfo' must be a dictionary containing all required keys."
                )

            if not isinstance(card_info["cardId"], int) or not isinstance(card_info["mod"], int):
                raise AnkiAPIUnexpectedResponse(
                    "Fields 'cardId' and 'mod' in 'cardsInfo' response must be integers."
                )
        return result

    def forget_cards(self, cards):
        """Forgets the given cards, making them new again.

        :param cards: A list of card IDs to forget.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(cards, list) or not all(isinstance(card, int) for card in cards):
            raise ValueError("Argument 'cards' must be a list of integers.")

        result = self.invoke("forgetCards", cards=cards)

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'forgetCards' must be null.")

        return result

    def relearn_cards(self, cards):
        """Marks the given cards as "relearning".

        :param cards: A list of card IDs to mark as relearning.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(cards, list) or not all(isinstance(card, int) for card in cards):
            raise ValueError("Argument 'cards' must be a list of integers.")

        result = self.invoke("relearnCards", cards=cards)

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'relearnCards' must be null.")

        return result

    def answer_cards(self, answers):
        """Answers cards with the specified ease values.

        :param answers: A list of dictionaries, each containing 'cardId' (int) and 'ease' (int between 1 and 4).
        :return: A list of booleans indicating success (True) or failure (False) for each card.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(answers, list) or not all(
            isinstance(answer, dict) and
            isinstance(answer.get("cardId"), int) and
            isinstance(answer.get("ease"), int) and 1 <= answer["ease"] <= 4
            for answer in answers
        ):
            raise ValueError(
                "Argument 'answers' must be a list of dictionaries with 'cardId' as an integer and 'ease' as an integer between 1 and 4."
            )

        result = self.invoke("answerCards", answers=answers)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(res, bool) for res in result):
            raise AnkiAPIUnexpectedResponse("API response for 'answerCards' must be a list of booleans.")

        return result

    def deck_names(self):
        """Gets the complete list of deck names for the current user.

        :return: A list of deck names.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = self.invoke("deckNames")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(deck, str) for deck in result):
            raise AnkiAPIUnexpectedResponse("API response for 'deckNames' must be a list of strings.")

        return result

    def deck_names_and_ids(self):
        """Gets the complete list of deck names and their respective IDs for the current user.

        :return: A dictionary with deck names as keys and their IDs as values.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = self.invoke("deckNamesAndIds")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, dict) or not all(
            isinstance(deck, str) and isinstance(deck_id, int) for deck, deck_id in result.items()
        ):
            raise AnkiAPIUnexpectedResponse("API response for 'deckNamesAndIds' must be a dictionary with strings as keys and integers as values.")

        return result

    def get_decks(self, cards):
        """Gets the decks and their respective card IDs for the given card IDs.

        :param cards: A list of card IDs to query.
        :return: A dictionary with deck names as keys and lists of card IDs as values.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(cards, list) or not all(isinstance(card, int) for card in cards):
            raise ValueError("Argument 'cards' must be a list of integers.")

        result = self.invoke("getDecks", cards=cards)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, dict) or not all(
            isinstance(deck, str) and isinstance(cards_list, list) and all(isinstance(card, int) for card in cards_list)
            for deck, cards_list in result.items()
        ):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'getDecks' must be a dictionary with strings as keys and lists of integers as values."
            )

        return result

    def create_deck(self, deck: str):
        """Creates a new empty deck.

        :param deck: The name of the deck to create.
        :return: The ID of the newly created deck.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(deck, str):
            raise ValueError("Argument 'deck' must be a string.")

        result = self.invoke("createDeck", deck=deck)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, int):
            raise AnkiAPIUnexpectedResponse("API response for 'createDeck' must be an integer.")

        return result

    def get_cards_in_deck(self, deck: str):
        return self.find_cards(f"deck:\"{deck}\"")

    def get_notes_in_deck(self, deck: str):
        return self.find_notes(f"deck:\"{deck}\"")

    def change_deck(self, cards, deck):
        """Moves the given cards to a different deck, creating the deck if it doesn’t exist.

        :param cards: A list of card IDs to move.
        :param deck: The name of the deck to move the cards to.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(cards, list) or not all(isinstance(card, int) for card in cards):
            raise ValueError("Argument 'cards' must be a list of integers.")

        if not isinstance(deck, str):
            raise ValueError("Argument 'deck' must be a string.")

        result = self.invoke("changeDeck", cards=cards, deck=deck)

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'changeDeck' must be null.")

        return result

    def delete_decks(self, decks, cards_too):
        """Deletes the given decks, optionally deleting their cards as well.

        :param decks: A list of deck names to delete.
        :param cards_too: A boolean indicating whether to delete the cards in the decks as well.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(decks, list) or not all(isinstance(deck, str) for deck in decks):
            raise ValueError("Argument 'decks' must be a list of strings.")

        if not isinstance(cards_too, bool):
            raise ValueError("Argument 'cards_too' must be a boolean.")

        result = self.invoke("deleteDecks", decks=decks, cardsToo=cards_too)

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'deleteDecks' must be null.")

        return result

    def get_deck_config(self, deck):
        """Gets the configuration group object for the given deck.

        :param deck: The name of the deck to retrieve the configuration for.
        :return: A dictionary containing the deck configuration.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(deck, str):
            raise ValueError("Argument 'deck' must be a string.")

        result = self.invoke("getDeckConfig", deck=deck)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, dict):
            raise AnkiAPIUnexpectedResponse("API response for 'getDeckConfig' must be a dictionary.")

        return result

    def save_deck_config(self, config):
        """Saves the given configuration group.

        :param config: A dictionary containing the configuration group to save.
        :return: True on success, False if the configuration ID is invalid.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(config, dict):
            raise ValueError("Argument 'config' must be a dictionary.")

        result = self.invoke("saveDeckConfig", config=config)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'saveDeckConfig' must be a boolean.")

        return result


    def set_deck_config_id(self, decks, config_id):
        """Changes the configuration group for the given decks to the specified ID.

        :param decks: A list of deck names to update.
        :param config_id: The ID of the configuration group to apply.
        :return: True on success, False otherwise.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(decks, list) or not all(isinstance(deck, str) for deck in decks):
            raise ValueError("Argument 'decks' must be a list of strings.")

        if not isinstance(config_id, int):
            raise ValueError("Argument 'config_id' must be an integer.")

        result = self.invoke("setDeckConfigId", decks=decks, configId=config_id)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'setDeckConfigId' must be a boolean.")

        return result

    def clone_deck_config_id(self, name, clone_from=None):
        """Creates a new configuration group with the given name, cloning from an existing group.

        :param name: The name of the new configuration group.
        :param clone_from: The ID of the configuration group to clone from (optional).
        :return: The ID of the new configuration group, or False if the specified group does not exist.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(name, str):
            raise ValueError("Argument 'name' must be a string.")

        if clone_from is not None and not isinstance(clone_from, int):
            raise ValueError("Argument 'clone_from' must be an integer if specified.")

        result = self.invoke("cloneDeckConfigId", name=name, cloneFrom=clone_from)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, (int, bool)):
            raise AnkiAPIUnexpectedResponse("API response for 'cloneDeckConfigId' must be an integer or a boolean.")

        return result

    def remove_deck_config_id(self, config_id):
        """Removes the configuration group with the given ID.

        :param config_id: The ID of the configuration group to remove.
        :return: True if successful, False otherwise.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(config_id, int):
            raise ValueError("Argument 'config_id' must be an integer.")

        result = self.invoke("removeDeckConfigId", configId=config_id)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'removeDeckConfigId' must be a boolean.")

        return result

    def get_deck_stats(self, decks):
        """Gets statistics such as total cards and cards due for the given decks.

        :param decks: A list of deck names to retrieve statistics for.
        :return: A dictionary with deck IDs as keys and statistics as values.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(decks, list) or not all(isinstance(deck, str) for deck in decks):
            raise ValueError("Argument 'decks' must be a list of strings.")

        result = self.invoke("getDeckStats", decks=decks)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, dict) or not all(
            isinstance(deck_id, str) and isinstance(stats, dict) and
            "deck_id" in stats and "name" in stats and "new_count" in stats and
            "learn_count" in stats and "review_count" in stats and "total_in_deck" in stats
            for deck_id, stats in result.items()
        ):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'getDeckStats' must be a dictionary with valid statistics for each deck."
            )

        return result

    def gui_browse(self, query, reorder_cards=None):
        """Invokes the Card Browser dialog and searches for a given query.

        :param query: The search query string.
        :param reorder_cards: A dictionary specifying the reorder options (optional).
        :return: A list of card identifiers that match the query.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(query, str):
            raise ValueError("Argument 'query' must be a string.")

        if reorder_cards is not None:
            if not isinstance(reorder_cards, dict) or not all(
                key in reorder_cards for key in ["order", "columnId"]
            ) or not isinstance(reorder_cards["order"], str) or not isinstance(reorder_cards["columnId"], str):
                raise ValueError(
                    "Argument 'reorder_cards' must be a dictionary with 'order' and 'columnId' as strings."
                )

        result = self.invoke("guiBrowse", query=query, reorderCards=reorder_cards)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(card_id, int) for card_id in result):
            raise AnkiAPIUnexpectedResponse("API response for 'guiBrowse' must be a list of integers.")

        return result

    def gui_select_card(self, card):
        """Finds the open instance of the Card Browser dialog and selects a note.

        :param card: The card identifier to select.
        :return: True if the Card Browser is open, False otherwise.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(card, int):
            raise ValueError("Argument 'note' must be an integer.")

        result = self.invoke("guiSelectCard", card=card)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'guiSelectNote' must be a boolean.")

        return result

    def gui_selected_notes(self):
        """Finds the open instance of the Card Browser dialog and returns selected note identifiers.

        :return: A list of note identifiers that are currently selected.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = self.invoke("guiSelectedNotes")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(note_id, int) for note_id in result):
            raise AnkiAPIUnexpectedResponse("API response for 'guiSelectedNotes' must be a list of integers.")

        return result

    def gui_add_card(self, note: Note):
        return self.add_note(note, True)

    def gui_edit_note(self, note):
        """Opens the Edit dialog for a note corresponding to the given note ID.

        :param note: The ID of the note to edit.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(note, int):
            raise ValueError("Argument 'note' must be an integer.")

        result = self.invoke("guiEditNote", note=note)

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'guiEditNote' must be null.")

        return result

    def gui_current_card(self):
        """Returns information about the current card or null if not in review mode.

        :return: A dictionary containing the current card information, or None if not in review mode.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = self.invoke("guiCurrentCard")

        if isinstance(result, DeferredResult):
            return result

        if result is not None and not isinstance(result, dict):
            raise AnkiAPIUnexpectedResponse("API response for 'guiCurrentCard' must be a dictionary or null.")

        return result

    def gui_start_card_timer(self):
        """Starts or resets the timer for the current card.

        :return: True if the timer was started or reset successfully, False otherwise.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = self.invoke("guiStartCardTimer")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'guiStartCardTimer' must be a boolean.")

        return result

    def gui_show_question(self):
        """Shows the question text for the current card.

        :return: True if in review mode, False otherwise.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = self.invoke("guiShowQuestion")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'guiShowQuestion' must be a boolean.")

        return result

    def gui_show_answer(self):
        """Shows the answer text for the current card.

        :return: True if in review mode, False otherwise.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = self.invoke("guiShowAnswer")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'guiShowAnswer' must be a boolean.")

        return result

    def gui_answer_card(self, ease):
        """Answers the current card.

        :param ease: An integer representing the ease level (1: Again, 2: Hard, 3: Good, 4: Easy).
        :return: True if the card was answered successfully, False otherwise.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(ease, int) or not (1 <= ease <= 4):
            raise ValueError("Argument 'ease' must be an integer between 1 and 4.")

        result = self.invoke("guiAnswerCard", ease=ease)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'guiAnswerCard' must be a boolean.")

        return result

    def gui_undo(self):
        """Undoes the last action or card.

        :return: True if the undo operation succeeded, False otherwise.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = self.invoke("guiUndo")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'guiUndo' must be a boolean.")

        return result

    def gui_deck_overview(self, name):
        """Opens the Deck Overview dialog for the specified deck.

        :param name: The name of the deck.
        :return: True if the operation succeeded, False otherwise.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(name, str):
            raise ValueError("Argument 'name' must be a string.")

        result = self.invoke("guiDeckOverview", name=name)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'guiDeckOverview' must be a boolean.")

        return result

    def gui_deck_browser(self):
        """Opens the Deck Browser dialog.

        :return: None
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = self.invoke("guiDeckBrowser")

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'guiDeckBrowser' must be null.")

        return result

    def gui_deck_review(self, name):
        """Starts review for the specified deck.

        :param name: The name of the deck.
        :return: True if the operation succeeded, False otherwise.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(name, str):
            raise ValueError("Argument 'name' must be a string.")

        result = self.invoke("guiDeckReview", name=name)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'guiDeckReview' must be a boolean.")

        return result

    def gui_import_file(self, path=None):
        """Invokes the Import dialog with an optional file path.

        :param path: The file path to import (optional).
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if path is not None and not isinstance(path, str):
            raise ValueError("Argument 'path' must be a string if provided.")

        result = self.invoke("guiImportFile", path=path)

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'guiImportFile' must be null.")

        return result

    def gui_exit_anki(self):
        """Schedules a request to gracefully close Anki.

        :return: None
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = self.invoke("guiExitAnki")

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'guiExitAnki' must be null.")

        return result

    def gui_check_database(self):
        """Requests a database check.

        :return: True, as this action always returns true regardless of errors during the check.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = self.invoke("guiCheckDatabase")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'guiCheckDatabase' must be a boolean.")

        return result

    def store_media_file(self, filename, data=None, path=None, url=None, delete_existing=True):
        """Stores a file in the media folder with the specified content, path, or URL.

        :param filename: The name of the file to store.
        :param data: Base64-encoded contents of the file (optional).
        :param path: Absolute file path to the content (optional).
        :param url: URL to download the file from (optional).
        :param delete_existing: Whether to delete an existing file with the same name (default: True).
        :return: The name of the stored file.
        :raises ValueError: If the input data type is incorrect or more than one data source is provided.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(filename, str):
            raise ValueError("Argument 'filename' must be a string.")

        if data is not None and not isinstance(data, str):
            raise ValueError("Argument 'data' must be a base64-encoded string if provided.")

        if path is not None and not isinstance(path, str):
            raise ValueError("Argument 'path' must be a string if provided.")

        if url is not None and not isinstance(url, str):
            raise ValueError("Argument 'url' must be a string if provided.")

        if not isinstance(delete_existing, bool):
            raise ValueError("Argument 'delete_existing' must be a boolean.")

        provided_sources = [data, path, url]
        if sum(source is not None for source in provided_sources) != 1:
            raise ValueError("Exactly one of 'data', 'path', or 'url' must be provided.")

        params = {
            "filename": filename,
            "data": data,
            "path": path,
            "url": url,
            "deleteExisting": delete_existing
        }

        # Remove keys with None values to avoid sending unnecessary parameters
        params = {key: value for key, value in params.items() if value is not None}

        result = self.invoke("storeMediaFile", **params)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, str):
            raise AnkiAPIUnexpectedResponse("API response for 'storeMediaFile' must be a string.")

        return result

    def retrieve_media_file(self, filename):
        """Retrieves the base64-encoded contents of the specified file.

        :param filename: The name of the file to retrieve.
        :return: The base64-encoded contents of the file, or False if the file does not exist.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(filename, str):
            raise ValueError("Argument 'filename' must be a string.")

        result = self.invoke("retrieveMediaFile", filename=filename)

        if isinstance(result, DeferredResult):
            return result

        if not (isinstance(result, str) or result is False):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'retrieveMediaFile' must be a base64-encoded string or False."
            )

        return result

    def get_media_files_names(self, pattern):
        """Gets the names of media files matching the specified pattern.

        :param pattern: The pattern to match filenames (optional).
        :return: A list of media file names matching the pattern.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if pattern is not None and not isinstance(pattern, str):
            raise ValueError("Argument 'pattern' must be a string if provided.")

        result = self.invoke("getMediaFilesNames", pattern=pattern)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(name, str) for name in result):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'getMediaFilesNames' must be a list of strings."
            )

        return result

    def get_media_dir_path(self):
        """Gets the full path to the collection.media folder of the currently opened profile.

        :return: The full path to the media directory.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = self.invoke("getMediaDirPath")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, str):
            raise AnkiAPIUnexpectedResponse("API response for 'getMediaDirPath' must be a string.")

        return result

    def delete_media_file(self, filename):
        """Deletes the specified file inside the media folder.

        :param filename: The name of the file to delete.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(filename, str):
            raise ValueError("Argument 'filename' must be a string.")

        result = self.invoke("deleteMediaFile", filename=filename)

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'deleteMediaFile' must be null.")

        return result

    def request_permission(self):
        """Requests permission to use the API exposed by this plugin.

        :return: A dictionary containing the permission status and additional information if permission is granted.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = self.invoke("requestPermission")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, dict) or "permission" not in result:
            raise AnkiAPIUnexpectedResponse(
                "API response for 'requestPermission' must be a dictionary containing the 'permission' field."
            )

        return result

    def version(self):
        """Gets the version of the API exposed by this plugin.

        :return: The API version as an integer.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = self.invoke("version")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, int):
            raise AnkiAPIUnexpectedResponse("API response for 'version' must be an integer.")

        return result

    def api_reflect(self, scopes=None, actions=None):
        """Gets information about the AnkiConnect APIs available.

        :param scopes: An optional list of scopes to get reflection information about.
        :param actions: An optional list of API method names to check for.
        :return: A dictionary containing reflection information about the available APIs.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if scopes is not None and not isinstance(scopes, list):
            raise ValueError("Argument 'scopes' must be a list if provided.")

        if actions is not None and not isinstance(actions, list):
            raise ValueError("Argument 'actions' must be a list if provided.")

        result = self.invoke("apiReflect", scopes=scopes, actions=actions)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, dict) or "scopes" not in result:
            raise AnkiAPIUnexpectedResponse(
                "API response for 'apiReflect' must be a dictionary containing the 'scopes' field."
            )

        return result

    def sync(self):
        """Synchronizes the local Anki collection with AnkiWeb.

        :return: None
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = self.invoke("sync")

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'sync' must be null.")

        return result

    def get_profiles(self):
        """Retrieves the list of profiles.

        :return: A list of profile names.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = self.invoke("getProfiles")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(profile, str) for profile in result):
            raise AnkiAPIUnexpectedResponse("API response for 'getProfiles' must be a list of strings.")

        return result

    def get_active_profile(self):
        """Retrieves the active profile.

        :return: The name of the active profile.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = self.invoke("getActiveProfile")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, str):
            raise AnkiAPIUnexpectedResponse("API response for 'getActiveProfile' must be a string.")

        return result

    def load_profile(self, name):
        """Selects the specified profile.

        :param name: The name of the profile to load.
        :return: True if the profile was successfully loaded, False otherwise.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(name, str):
            raise ValueError("Argument 'name' must be a string.")

        result = self.invoke("loadProfile", name=name)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'loadProfile' must be a boolean.")

        return result

    def export_package(self, deck, path, include_sched=False):
        """Exports a given deck in .apkg format.

        :param deck: The name of the deck to export.
        :param path: The file path to save the .apkg file.
        :param include_sched: Whether to include the cards' scheduling data (default: False).
        :return: True if the export was successful, False otherwise.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(deck, str):
            raise ValueError("Argument 'deck' must be a string.")

        if not isinstance(path, str):
            raise ValueError("Argument 'path' must be a string.")

        if not isinstance(include_sched, bool):
            raise ValueError("Argument 'include_sched' must be a boolean.")

        result = self.invoke("exportPackage", deck=deck, path=path, includeSched=include_sched)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'exportPackage' must be a boolean.")

        return result

    def import_package(self, path):
        """Imports a .apkg file into the collection.

        :param path: The file path to the .apkg file (relative to Anki's collection.media folder).
        :return: True if the import was successful, False otherwise.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(path, str):
            raise ValueError("Argument 'path' must be a string.")

        result = self.invoke("importPackage", path=path)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'importPackage' must be a boolean.")

        return result

    def reload_collection(self):
        """Tells Anki to reload all data from the database.

        :return: None
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = self.invoke("reloadCollection")

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'reloadCollection' must be null.")

        return result

    def model_names(self):
        """Gets the complete list of model names for the current user.

        :return: A list of model names.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = self.invoke("modelNames")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(name, str) for name in result):
            raise AnkiAPIUnexpectedResponse("API response for 'modelNames' must be a list of strings.")

        return result

    def model_names_and_ids(self):
        """Gets the complete list of model names and their corresponding IDs for the current user.

        :return: A dictionary with model names as keys and their IDs as values.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = self.invoke("modelNamesAndIds")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, dict) or not all(
            isinstance(name, str) and isinstance(model_id, int) for name, model_id in result.items()
        ):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'modelNamesAndIds' must be a dictionary with strings as keys and integers as values."
            )

        return result

    def find_models_by_id(self, model_ids):
        """Gets a list of models for the provided model IDs from the current user.

        :param model_ids: A list of model IDs to retrieve.
        :return: A list of dictionaries containing model details.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_ids, list) or not all(isinstance(model_id, int) for model_id in model_ids):
            raise ValueError("Argument 'model_ids' must be a list of integers.")

        result = self.invoke("findModelsById", modelIds=model_ids)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(model, dict) for model in result):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'findModelsById' must be a list of dictionaries."
            )

        return result

    def find_models_by_name(self, model_names):
        """Gets a list of models for the provided model names from the current user.

        :param model_names: A list of model names to retrieve.
        :return: A list of dictionaries containing model details.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_names, list) or not all(isinstance(name, str) for name in model_names):
            raise ValueError("Argument 'model_names' must be a list of strings.")

        result = self.invoke("findModelsByName", modelNames=model_names)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(model, dict) for model in result):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'findModelsByName' must be a list of dictionaries."
            )

        return result

    def model_field_names(self, model_name):
        """Gets the complete list of field names for the provided model name.

        :param model_name: The name of the model to retrieve field names for.
        :return: A list of field names.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_name, str):
            raise ValueError("Argument 'model_name' must be a string.")

        result = self.invoke("modelFieldNames", modelName=model_name)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(field_name, str) for field_name in result):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'modelFieldNames' must be a list of strings."
            )

        return result

    def model_field_descriptions(self, model_name):
        """Gets the complete list of field descriptions for the provided model name.

        :param model_name: The name of the model to retrieve field descriptions for.
        :return: A list of field descriptions.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_name, str):
            raise ValueError("Argument 'model_name' must be a string.")

        result = self.invoke("modelFieldDescriptions", modelName=model_name)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(description, str) for description in result):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'modelFieldDescriptions' must be a list of strings."
            )

        return result

    def model_field_fonts(self, model_name):
        """Gets the complete list of fonts along with their font sizes for the specified model.

        :param model_name: The name of the model to retrieve font details for.
        :return: A dictionary with field names as keys and font details as values.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_name, str):
            raise ValueError("Argument 'model_name' must be a string.")

        result = self.invoke("modelFieldFonts", modelName=model_name)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, dict) or not all(
            isinstance(field, str) and isinstance(details, dict) and "font" in details and "size" in details and
            isinstance(details["font"], str) and isinstance(details["size"], int)
            for field, details in result.items()
        ):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'modelFieldFonts' must be a dictionary with valid font details."
            )

        return result

    def model_fields_on_templates(self, model_name):
        """Returns the fields on the question and answer sides of each card template for the specified model.

        :param model_name: The name of the model to retrieve fields on templates for.
        :return: A dictionary with template names as keys and lists of fields as values.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_name, str):
            raise ValueError("Argument 'model_name' must be a string.")

        result = self.invoke("modelFieldsOnTemplates", modelName=model_name)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, dict) or not all(
            isinstance(template, str) and isinstance(fields, list) and
            len(fields) == 2 and all(isinstance(field_list, list) and all(isinstance(field, str) for field in field_list) for field_list in fields)
            for template, fields in result.items()
        ):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'modelFieldsOnTemplates' must be a dictionary with valid template field details."
            )

        return result

    def create_model(self, model_name, in_order_fields, card_templates, css=None, is_cloze=False):
        """Creates a new model to be used in Anki.

        :param model_name: The name of the new model.
        :param in_order_fields: A list of field names in the order they should appear.
        :param card_templates: A list of dictionaries defining card templates.
        :param css: Optional CSS for the model (default: Anki's built-in CSS).
        :param is_cloze: Whether the model should be created as Cloze (default: False).
        :return: A dictionary containing the created model details.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_name, str):
            raise ValueError("Argument 'model_name' must be a string.")

        if not isinstance(in_order_fields, list) or not all(isinstance(field, str) for field in in_order_fields):
            raise ValueError("Argument 'in_order_fields' must be a list of strings.")

        if not isinstance(card_templates, list) or not all(
            isinstance(template, dict) and "Front" in template and "Back" in template
            for template in card_templates
        ):
            raise ValueError(
                "Argument 'card_templates' must be a list of dictionaries with 'Front' and 'Back' keys."
            )

        if css is not None and not isinstance(css, str):
            raise ValueError("Argument 'css' must be a string if provided.")

        if not isinstance(is_cloze, bool):
            raise ValueError("Argument 'is_cloze' must be a boolean.")

        result = self.invoke(
            "createModel",
            modelName=model_name,
            inOrderFields=in_order_fields,
            css=css,
            isCloze=is_cloze,
            cardTemplates=card_templates
        )

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, dict):
            raise AnkiAPIUnexpectedResponse("API response for 'createModel' must be a dictionary.")

        return result

    def model_templates(self, model_name):
        """Gets the template content for each card connected to the provided model by name.

        :param model_name: The name of the model to retrieve templates for.
        :return: A dictionary with card names as keys and template content as values.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_name, str):
            raise ValueError("Argument 'model_name' must be a string.")

        result = self.invoke("modelTemplates", modelName=model_name)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, dict) or not all(
            isinstance(card, str) and isinstance(content, dict) and "Front" in content and "Back" in content
            for card, content in result.items()
        ):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'modelTemplates' must be a dictionary with valid card template content."
            )

        return result

    def model_styling(self, model_name):
        """Gets the CSS styling for the provided model by name.

        :param model_name: The name of the model to retrieve styling for.
        :return: A dictionary containing the CSS styling.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_name, str):
            raise ValueError("Argument 'model_name' must be a string.")

        result = self.invoke("modelStyling", modelName=model_name)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, dict) or "css" not in result or not isinstance(result["css"], str):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'modelStyling' must be a dictionary containing the 'css' field."
            )

        return result

    def update_model_templates(self, model_name, templates):
        """Modifies the templates of an existing model by name.

        :param model_name: The name of the model to update.
        :param templates: A dictionary specifying the templates to modify.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_name, str):
            raise ValueError("Argument 'model_name' must be a string.")

        if not isinstance(templates, dict) or not all(
            isinstance(card, str) and isinstance(content, dict) and "Front" in content and "Back" in content
            for card, content in templates.items()
        ):
            raise ValueError(
                "Argument 'templates' must be a dictionary with card names as keys and dictionaries containing 'Front' and 'Back' keys as values."
            )

        result = self.invoke("updateModelTemplates", model={"name": model_name, "templates": templates})

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'updateModelTemplates' must be null.")

        return result

    def update_model_styling(self, model_name, css):
        """Modifies the CSS styling of an existing model by name.

        :param model_name: The name of the model to update.
        :param css: The CSS styling to apply to the model.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_name, str):
            raise ValueError("Argument 'model_name' must be a string.")

        if not isinstance(css, str):
            raise ValueError("Argument 'css' must be a string.")

        result = self.invoke("updateModelStyling", model={"name": model_name, "css": css})

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'updateModelStyling' must be null.")

        return result

    def find_and_replace_in_models(self, model_name, find_text, replace_text, front=False, back=False, css=False):
        """Finds and replaces a string in an existing model by model name.

        :param model_name: The name of the model.
        :param find_text: The text to find.
        :param replace_text: The text to replace with.
        :param front: Whether to replace in the front template (default: False).
        :param back: Whether to replace in the back template (default: False).
        :param css: Whether to replace in the CSS (default: False).
        :return: The number of replacements made.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_name, str):
            raise ValueError("Argument 'model_name' must be a string.")

        if not isinstance(find_text, str):
            raise ValueError("Argument 'find_text' must be a string.")

        if not isinstance(replace_text, str):
            raise ValueError("Argument 'replace_text' must be a string.")

        if not all(isinstance(flag, bool) for flag in [front, back, css]):
            raise ValueError("Arguments 'front', 'back', and 'css' must be booleans.")

        result = self.invoke(
            "findAndReplaceInModels",
            model={
                "modelName": model_name,
                "findText": find_text,
                "replaceText": replace_text,
                "front": front,
                "back": back,
                "css": css,
            },
        )

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, int):
            raise AnkiAPIUnexpectedResponse("API response for 'findAndReplaceInModels' must be an integer.")

        return result

    def model_template_rename(self, model_name, old_template_name, new_template_name):
        """Renames a template in an existing model.

        :param model_name: The name of the model.
        :param old_template_name: The current name of the template.
        :param new_template_name: The new name for the template.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_name, str):
            raise ValueError("Argument 'model_name' must be a string.")

        if not isinstance(old_template_name, str):
            raise ValueError("Argument 'old_template_name' must be a string.")

        if not isinstance(new_template_name, str):
            raise ValueError("Argument 'new_template_name' must be a string.")

        result = self.invoke(
            "modelTemplateRename",
            modelName=model_name,
            oldTemplateName=old_template_name,
            newTemplateName=new_template_name,
        )

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'modelTemplateRename' must be null.")

        return result

    def model_template_reposition(self, model_name, template_name, index):
        """Repositions a template in an existing model.

        :param model_name: The name of the model.
        :param template_name: The name of the template to reposition.
        :param index: The new index position for the template (starting at 0).
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_name, str):
            raise ValueError("Argument 'model_name' must be a string.")

        if not isinstance(template_name, str):
            raise ValueError("Argument 'template_name' must be a string.")

        if not isinstance(index, int):
            raise ValueError("Argument 'index' must be an integer.")

        result = self.invoke(
            "modelTemplateReposition",
            modelName=model_name,
            templateName=template_name,
            index=index,
        )

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'modelTemplateReposition' must be null.")

        return result

    def model_template_add(self, model_name, template):
        """Adds a template to an existing model by name.

        :param model_name: The name of the model.
        :param template: A dictionary defining the template to add (must include 'Name', 'Front', and 'Back').
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_name, str):
            raise ValueError("Argument 'model_name' must be a string.")

        if not isinstance(template, dict) or not all(
            key in template for key in ["Name", "Front", "Back"]
        ):
            raise ValueError(
                "Argument 'template' must be a dictionary containing 'Name', 'Front', and 'Back'."
            )

        result = self.invoke("modelTemplateAdd", modelName=model_name, template=template)

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'modelTemplateAdd' must be null.")

        return result

    def model_template_remove(self, model_name, template_name):
        """Removes a template from an existing model.

        :param model_name: The name of the model.
        :param template_name: The name of the template to remove.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_name, str):
            raise ValueError("Argument 'model_name' must be a string.")

        if not isinstance(template_name, str):
            raise ValueError("Argument 'template_name' must be a string.")

        result = self.invoke(
            "modelTemplateRemove",
            modelName=model_name,
            templateName=template_name,
        )

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'modelTemplateRemove' must be null.")

        return result
    def model_field_rename(self, model_name, old_field_name, new_field_name):
        """Renames the field name of a given model.

        :param model_name: The name of the model.
        :param old_field_name: The current name of the field.
        :param new_field_name: The new name for the field.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not all(isinstance(arg, str) for arg in [model_name, old_field_name, new_field_name]):
            raise ValueError("Arguments 'model_name', 'old_field_name', and 'new_field_name' must be strings.")

        result = self.invoke(
            "modelFieldRename",
            modelName=model_name,
            oldFieldName=old_field_name,
            newFieldName=new_field_name,
        )

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'modelFieldRename' must be null.")

        return result

    def model_field_reposition(self, model_name, field_name, index):
        """Repositions the field within the field list of a given model.

        :param model_name: The name of the model.
        :param field_name: The name of the field to reposition.
        :param index: The new index position for the field (starting at 0).
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not all(isinstance(arg, str) for arg in [model_name, field_name]):
            raise ValueError("Arguments 'model_name' and 'field_name' must be strings.")

        if not isinstance(index, int):
            raise ValueError("Argument 'index' must be an integer.")

        result = self.invoke(
            "modelFieldReposition",
            modelName=model_name,
            fieldName=field_name,
            index=index,
        )

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'modelFieldReposition' must be null.")

        return result

    def model_field_add(self, model_name, field_name, index=None):
        """Creates a new field within a given model.

        :param model_name: The name of the model.
        :param field_name: The name of the new field.
        :param index: Optional index value for positioning the field (default: added to the end).
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not all(isinstance(arg, str) for arg in [model_name, field_name]):
            raise ValueError("Arguments 'model_name' and 'field_name' must be strings.")

        if index is not None and not isinstance(index, int):
            raise ValueError("Argument 'index' must be an integer if provided.")

        params = {"modelName": model_name, "fieldName": field_name}
        if index is not None:
            params["index"] = index

        result = self.invoke("modelFieldAdd", **params)

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'modelFieldAdd' must be null.")

        return result

    def model_field_remove(self, model_name, field_name):
        """Deletes a field within a given model.

        :param model_name: The name of the model.
        :param field_name: The name of the field to remove.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not all(isinstance(arg, str) for arg in [model_name, field_name]):
            raise ValueError("Arguments 'model_name' and 'field_name' must be strings.")

        result = self.invoke(
            "modelFieldRemove",
            modelName=model_name,
            fieldName=field_name,
        )

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'modelFieldRemove' must be null.")

        return result

    def model_field_set_font(self, model_name, field_name, font):
        """Sets the font for a field within a given model.

        :param model_name: The name of the model.
        :param field_name: The name of the field.
        :param font: The font to set for the field.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not all(isinstance(arg, str) for arg in [model_name, field_name, font]):
            raise ValueError("Arguments 'model_name', 'field_name', and 'font' must be strings.")

        result = self.invoke(
            "modelFieldSetFont",
            modelName=model_name,
            fieldName=field_name,
            font=font,
        )

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'modelFieldSetFont' must be null.")

        return result

    def model_field_set_font_size(self, model_name, field_name, font_size):
        """Sets the font size for a field within a given model.

        :param model_name: The name of the model.
        :param field_name: The name of the field.
        :param font_size: The font size to set for the field.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(model_name, str):
            raise ValueError("Argument 'model_name' must be a string.")

        if not isinstance(field_name, str):
            raise ValueError("Argument 'field_name' must be a string.")

        if not isinstance(font_size, int):
            raise ValueError("Argument 'font_size' must be an integer.")

        result = self.invoke(
            "modelFieldSetFontSize",
            modelName=model_name,
            fieldName=field_name,
            fontSize=font_size,
        )

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'modelFieldSetFontSize' must be null.")

        return result

    def model_field_set_description(self, model_name, field_name, description):
        """Sets the description for a field within a given model.

        :param model_name: The name of the model.
        :param field_name: The name of the field.
        :param description: The description to set for the field.
        :return: True if successful, False otherwise.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not all(isinstance(arg, str) for arg in [model_name, field_name, description]):
            raise ValueError("Arguments 'model_name', 'field_name', and 'description' must be strings.")

        result = self.invoke(
            "modelFieldSetDescription",
            modelName=model_name,
            fieldName=field_name,
            description=description,
        )

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, bool):
            raise AnkiAPIUnexpectedResponse("API response for 'modelFieldSetDescription' must be a boolean.")

        return result

    def update_note_tags(self, note_id, tags):
        """Set a note's tags by note ID. Old tags will be removed.

        :param note_id: The ID of the note to update.
        :param tags: A list of tags to set for the note.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(note_id, int):
            raise ValueError("Argument 'note_id' must be an integer.")

        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise ValueError("Argument 'tags' must be a list of strings.")

        result = self.invoke("updateNoteTags", note=note_id, tags=tags)

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'updateNoteTags' must be null.")

        return result

    def get_note_tags(self, note_id):
        """Get a note's tags by note ID.

        :param note_id: The ID of the note to retrieve tags for.
        :return: A list of tags associated with the note.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(note_id, int):
            raise ValueError("Argument 'note_id' must be an integer.")

        result = self.invoke("getNoteTags", note=note_id)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(tag, str) for tag in result):
            raise AnkiAPIUnexpectedResponse("API response for 'getNoteTags' must be a list of strings.")

        return result

    def add_tags(self, note_ids, tags):
        """Adds tags to notes by note ID.

        :param note_ids: A list of note IDs to add tags to.
        :param tags: A string of tags to add, separated by spaces.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(note_ids, list) or not all(isinstance(note_id, int) for note_id in note_ids):
            raise ValueError("Argument 'note_ids' must be a list of integers.")

        if not isinstance(tags, str):
            raise ValueError("Argument 'tags' must be a string.")

        result = self.invoke("addTags", notes=note_ids, tags=tags)

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'addTags' must be null.")

        return result

    def remove_tags(self, note_ids, tags):
        """Removes tags from notes by note ID.

        :param note_ids: A list of note IDs to remove tags from.
        :param tags: A string of tags to remove, separated by spaces.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(note_ids, list) or not all(isinstance(note_id, int) for note_id in note_ids):
            raise ValueError("Argument 'note_ids' must be a list of integers.")

        if not isinstance(tags, str):
            raise ValueError("Argument 'tags' must be a string.")

        result = self.invoke("removeTags", notes=note_ids, tags=tags)

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'removeTags' must be null.")

        return result

    def get_tags(self):
        """Gets the complete list of tags for the current user.

        :return: A list of tags.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = self.invoke("getTags")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(tag, str) for tag in result):
            raise AnkiAPIUnexpectedResponse("API response for 'getTags' must be a list of strings.")

        return result

    def clear_unused_tags(self):
        """Clears all the unused tags in the notes for the current user.

        :return: None
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = self.invoke("clearUnusedTags")

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'clearUnusedTags' must be null.")

        return result

    def replace_tags(self, notes, tag_to_replace, replace_with_tag):
        """Replaces tags in notes by note ID.

        :param notes: A list of note IDs to replace tags in.
        :param tag_to_replace: The tag to replace.
        :param replace_with_tag: The tag to replace with.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(notes, list) or not all(isinstance(note, int) for note in notes):
            raise ValueError("Argument 'notes' must be a list of integers.")

        if not isinstance(tag_to_replace, str):
            raise ValueError("Argument 'tag_to_replace' must be a string.")

        if not isinstance(replace_with_tag, str):
            raise ValueError("Argument 'replace_with_tag' must be a string.")

        result = self.invoke(
            "replaceTags",
            notes=notes,
            tag_to_replace=tag_to_replace,
            replace_with_tag=replace_with_tag,
        )

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'replaceTags' must be null.")

        return result

    def replace_tags_in_all_notes(self, tag_to_replace, replace_with_tag):
        """Replaces tags in all notes for the current user.

        :param tag_to_replace: The tag to replace.
        :param replace_with_tag: The tag to replace with.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(tag_to_replace, str):
            raise ValueError("Argument 'tag_to_replace' must be a string.")

        if not isinstance(replace_with_tag, str):
            raise ValueError("Argument 'replace_with_tag' must be a string.")

        result = self.invoke(
            "replaceTagsInAllNotes",
            tag_to_replace=tag_to_replace,
            replace_with_tag=replace_with_tag,
        )

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'replaceTagsInAllNotes' must be null.")

        return result

    def find_notes(self, query):
        """Returns an array of note IDs for a given query.

        :param query: The search query string.
        :return: A list of note IDs matching the query.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(query, str):
            raise ValueError("Argument 'query' must be a string.")

        result = self.invoke("findNotes", query=query)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(note_id, int) for note_id in result):
            raise AnkiAPIUnexpectedResponse("API response for 'findNotes' must be a list of integers.")

        return result

    def notes_info(self, note_ids):
        """Returns a list of objects containing detailed information for each note ID.

        :param note_ids: A list of note IDs to retrieve information for.
        :return: A list of dictionaries containing note details.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(note_ids, list) or not all(isinstance(note_id, int) for note_id in note_ids):
            raise ValueError("Argument 'note_ids' must be a list of integers.")

        result = self.invoke("notesInfo", notes=note_ids)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(note, dict) for note in result):
            raise AnkiAPIUnexpectedResponse("API response for 'notesInfo' must be a list of dictionaries.")

        return result

    def notes_mod_time(self, note_ids):
        """Returns a list of objects containing the modification time for each note ID.

        :param note_ids: A list of note IDs to retrieve modification times for.
        :return: A list of dictionaries containing note ID and modification time.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(note_ids, list) or not all(isinstance(note_id, int) for note_id in note_ids):
            raise ValueError("Argument 'note_ids' must be a list of integers.")

        result = self.invoke("notesModTime", notes=note_ids)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(
            isinstance(note, dict) and "noteId" in note and "mod" in note and
            isinstance(note["noteId"], int) and isinstance(note["mod"], int)
            for note in result
        ):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'notesModTime' must be a list of dictionaries with 'noteId' and 'mod' keys."
            )

        return result

    def delete_notes(self, note_ids):
        """Deletes notes with the given IDs. All associated cards will also be deleted.

        :param note_ids: A list of note IDs to delete.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(note_ids, list) or not all(isinstance(note_id, int) for note_id in note_ids):
            raise ValueError("Argument 'note_ids' must be a list of integers.")

        result = self.invoke("deleteNotes", notes=note_ids)

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'deleteNotes' must be null.")

        return result

    def remove_empty_notes(self):
        """Removes all empty notes for the current user.

        :return: None
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = self.invoke("removeEmptyNotes")

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'removeEmptyNotes' must be null.")

        return result

    def get_num_cards_reviewed_today(self):
        """Gets the count of cards that have been reviewed today.

        :return: The number of cards reviewed today.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = self.invoke("getNumCardsReviewedToday")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, int):
            raise AnkiAPIUnexpectedResponse("API response for 'getNumCardsReviewedToday' must be an integer.")

        return result

    def get_num_cards_reviewed_by_day(self):
        """Gets the number of cards reviewed as a list of pairs (dateString, number).

        :return: A list of tuples containing date strings and review counts.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = self.invoke("getNumCardsReviewedByDay")

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(
            isinstance(item, list) and len(item) == 2 and isinstance(item[0], str) and isinstance(item[1], int)
            for item in result
        ):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'getNumCardsReviewedByDay' must be a list of [dateString, integer] pairs."
            )

        return result

    def get_collection_stats_html(self, whole_collection=True):
        """Gets the collection statistics report in HTML format.

        :param whole_collection: Whether to get stats for the whole collection (default: True).
        :return: The HTML report as a string.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(whole_collection, bool):
            raise ValueError("Argument 'whole_collection' must be a boolean.")

        result = self.invoke("getCollectionStatsHTML", wholeCollection=whole_collection)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, str):
            raise AnkiAPIUnexpectedResponse("API response for 'getCollectionStatsHTML' must be a string.")

        return result

    def card_reviews(self, deck, start_id):
        """Requests all card reviews for a specified deck after a certain time.

        :param deck: The name of the deck to query.
        :param start_id: The latest Unix time not included in the result.
        :return: A list of 9-tuples with review data.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(deck, str):
            raise ValueError("Argument 'deck' must be a string.")

        if not isinstance(start_id, int):
            raise ValueError("Argument 'start_id' must be an integer.")

        result = self.invoke("cardReviews", deck=deck, startID=start_id)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(
            isinstance(item, list) and len(item) == 9 and all(isinstance(value, (int, float)) for value in item)
            for item in result
        ):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'cardReviews' must be a list of 9-tuples with numerical values."
            )

        return result

    def get_reviews_of_cards(self, card_ids):
        """Requests all card reviews for each card ID.

        :param card_ids: A list of card IDs to retrieve reviews for.
        :return: A dictionary mapping each card ID to a list of review dictionaries.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(card_ids, list) or not all(isinstance(card_id, int) for card_id in card_ids):
            raise ValueError("Argument 'card_ids' must be a list of integers.")

        result = self.invoke("getReviewsOfCards", cards=card_ids)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, dict) or not all(
            isinstance(card_id, str) and isinstance(reviews, list) and all(
                isinstance(review, dict) and all(
                    key in review for key in ["id", "usn", "ease", "ivl", "lastIvl", "factor", "time", "type"]
                ) for review in reviews
            )
            for card_id, reviews in result.items()
        ):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'getReviewsOfCards' must be a dictionary mapping card IDs to lists of review dictionaries."
            )

        return result

    def get_latest_review_id(self, deck):
        """Returns the unix time of the latest review for the given deck.

        :param deck: The name of the deck to query.
        :return: The Unix time of the latest review, or 0 if no reviews exist.
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(deck, str):
            raise ValueError("Argument 'deck' must be a string.")

        result = self.invoke("getLatestReviewID", deck=deck)

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, int):
            raise AnkiAPIUnexpectedResponse("API response for 'getLatestReviewID' must be an integer.")

        return result

    def insert_reviews(self, reviews):
        """Inserts the given reviews into the database.

        :param reviews: A list of 9-tuples representing review data.
        :return: None
        :raises ValueError: If the input data type is incorrect.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        if not isinstance(reviews, list) or not all(
            isinstance(review, (list, tuple)) and len(review) == 9 and all(
                isinstance(value, (int, float)) for value in review
            )
            for review in reviews
        ):
            raise ValueError(
                "Argument 'reviews' must be a list of 9-tuples with numerical values."
            )

        result = self.invoke("insertReviews", reviews=reviews)

        if isinstance(result, DeferredResult):
            return result

        if result is not None:
            raise AnkiAPIUnexpectedResponse("API response for 'insertReviews' must be null.")

        return result

    def add_notes(self, notes: List[Note]):
        """
        Inserts the given notes into the Anki collection.

        It should be noted that there is a subtle difference between an `addNotes`
        action and a `multi` action composed of many individual `addNote` actions.
        In the latter case, add notes

        :param notes: the notes to add.
        :raises ValueError: If the input data type is incorrect or required fields are missing.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        result = self.invoke('addNotes', notes=[note.to_anki_params() for note in notes])

        if isinstance(result, DeferredResult):
            return result

        if not isinstance(result, list) or not all(isinstance(item, int) for item in result):
            raise AnkiAPIUnexpectedResponse(
                "API response for 'addNotes' must be a list of cards added."
            )
        return result

    def can_add_notes(self, notes: List[Note], detailed=False):
        """
        Inserts the given notes into the Anki collection.
        :param notes: the notes to add.
        :param detailed: If True, return a detailed version of the errors when something goes wrong.
        :raises ValueError: If the input data type is incorrect or required fields are missing.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        api_name = "canAddNotesWithErrorDetail" if detailed else "canAddNotes"
        result = self.invoke(api_name, notes=[note.to_anki_params() for note in notes])

        if isinstance(result, DeferredResult):
            return result

        if result is not None and not isinstance(result, list):
            raise AnkiAPIUnexpectedResponse(f"API response for '{api_name}' must be a list.")
        return result

    def add_note(self, note: Note, open_gui=False):
        """Creates a note using the given deck and model, with the provided field values and tags.
        :raises ValueError: If the input data type is incorrect or required fields are missing.
        :raises AnkiAPIUnexpectedResponse: If the API response format is invalid.
        :raises Exception: If the API request fails or returns an error.
        """
        api_name = "guiAddCards" if open_gui else "addNote"
        result = self.invoke(api_name, note=note.to_anki_params())

        if isinstance(result, DeferredResult):
            return result

        if result is not None and not isinstance(result, int):
            raise AnkiAPIUnexpectedResponse(f"API response for '{api_name}' must be an integer.")
        return result

    # MARK: Constructive Actions

    def add_vocab_card(self, deck_name: str, front: str, back: str, examples: str, open_gui = False, images: List[Resource] = None, tags: List[str] = None):
        return self.add_note(
            Note.make_basic_card(deck_name, front, back, examples, images, tags),
            open_gui=open_gui,
        )

    def gui_add_vocab_card(self, deck_name: str, front: str, back: str, examples: str, images: List[Resource] = None, tags: List[str] = None):
        return self.add_vocab_card(deck_name=deck_name, front=front, back=back, examples=examples, open_gui=True, images=images, tags=tags)
