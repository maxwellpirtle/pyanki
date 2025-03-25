import enum

class Action(enum.Enum):
    # Read-only Card Actions
    GET_CARDS = "findCards"
    GET_CARDS_EASE_FACTORS = "getEaseFactors"
    GET_CARDS_INTERVALS = "getIntervals"
    GET_CARDS_SUSPENDED_STATUS = "areSuspended"
    GET_CARDS_DUE_STATUS = "areDue"
    GET_CARDS_INFO = "cardsInfo"
    GET_CARDS_MOD_TIME = "cardsModTime"

    # Read-write Card Actions
    SET_EASE_FACTORS = "setEaseFactors"
    SET_SPECIFIC_VALUE_OF_CARD = "setSpecificValueOfCard"
    SUSPEND_CARD = "suspend"
    UNSUSPEND_CARD = "unsuspend"
    ANSWER_CARDS = "answerCards"
    FORGET_CARDS = "forgetCards"
    RELEARN_CARDS = "relearnCards"
    SYNC_CARDS = "syncCards"

    # Read-only Deck Actions
    GET_DECK_NAMES = "deckNames"
    GET_DECK_NAMES_AND_IDS = "deckNamesAndIds"
    GET_DECKS_FOR_CARDS = "getDecks"
    GET_DECK_CONFIG = "getDeckConfig"
    GET_DECK_STATS = "getDeckStats"

    # Read-write Deck Actions
    CREATE_DECK = "createDeck"
    CHANGE_DECK = "changeDeck"
    DELETE_DECKS = "deleteDecks"
    SAVE_DECK_CONFIG = "saveDeckConfig"
    SET_DECK_CONFIG_ID = "setDeckConfigId"
    CLONE_DECK_CONFIG_ID = "cloneDeckConfigId"
    REMOVE_DECK_CONFIG_ID = "removeDeckConfigId"

    # GUI Actions
    GUI_BROWSE = "guiBrowse"
    GUI_SELECT_NOTE = "guiSelectNote"
    GUI_SELECTED_NOTES = "guiSelectedNotes"
    GUI_ADD_CARDS = "guiAddCards"
    GUI_EDIT_NOTE = "guiEditNote"
    GUI_CURRENT_CARD = "guiCurrentCard"
    GUI_START_CARD_TIMER = "guiStartCardTimer"
    GUI_SHOW_QUESTION = "guiShowQuestion"
    GUI_SHOW_ANSWER = "guiShowAnswer"
    GUI_ANSWER_CARD = "guiAnswerCard"
    GUI_UNDO = "guiUndo"
    GUI_DECK_OVERVIEW = "guiDeckOverview"
    GUI_DECK_BROWSER = "guiDeckBrowser"
    GUI_DECK_REVIEW = "guiDeckReview"
    GUI_IMPORT_FILE = "guiImportFile"
    GUI_EXIT_ANKI = "guiExitAnki"
    GUI_CHECK_DATABASE = "guiCheckDatabase"

    # Media Actions
    GET_MEDIA_FILES_NAMES = "getMediaFilesNames"
    GET_MEDIA_DIR_PATH = "getMediaDirPath"

    STORE_MEDIA_FILE = "storeMediaFile"
    RETRIEVE_MEDIA_FILE = "retrieveMediaFile"
    DELETE_MEDIA_FILE = "deleteMediaFile"

    # Miscellaneous Actions
    GET_VERSION = "version"
    GET_PROFILES = "getProfiles"
    GET_ACTIVE_PROFILE = "getActiveProfile"
    API_REFLECT = "apiReflect"
    MULTI = "multi"
    REQUEST_PERMISSION = "requestPermission"
    SYNC_DATABASE = "sync"
    LOAD_PROFILE = "loadProfile"
    EXPORT_PACKAGE = "exportPackage"
    IMPORT_PACKAGE = "importPackage"
    RELOAD_COLLECTION = "reloadCollection"

    # Model Actions
    GET_MODEL_NAMES = "modelNames"
    GET_MODEL_NAMES_AND_IDS = "modelNamesAndIds"
    GET_MODEL_FIELD_NAMES = "modelFieldNames"
    GET_MODEL_FIELD_DESCRIPTIONS = "modelFieldDescriptions"
    GET_MODEL_FIELD_FONTS = "modelFieldFonts"
    GET_MODEL_FIELDS_ON_TEMPLATES = "modelFieldsOnTemplates"
    GET_MODEL_TEMPLATES = "modelTemplates"
    GET_MODEL_STYLING = "modelStyling"
    FIND_MODELS_BY_ID = "findModelsById"
    FIND_MODELS_BY_NAME = "findModelsByName"

    CREATE_MODEL = "createModel"
    ADD_MODEL_TEMPLATE = "modelTemplateAdd"
    ADD_MODEL_FIELD = "modelFieldAdd"

    UPDATE_MODEL_TEMPLATES = "updateModelTemplates"
    UPDATE_MODEL_STYLING = "updateModelStyling"
    RENAME_MODEL_TEMPLATE = "modelTemplateRename"
    REPOSITION_MODEL_TEMPLATE = "modelTemplateReposition"
    REPOSITION_MODEL_FIELD = "modelFieldReposition"
    REMOVE_MODEL_TEMPLATE = "modelTemplateRemove"
    RENAME_MODEL_FIELD = "modelFieldRename"
    REMOVE_MODEL_FIELD = "modelFieldRemove"
    FIND_AND_REPLACE_IN_MODELS = "findAndReplaceInModels"

    SET_MODEL_FIELD_FONT = "modelFieldSetFont"
    SET_MODEL_FIELD_FONT_SIZE = "modelFieldSetFontSize"
    SET_MODEL_FIELD_DESCRIPTION = "modelFieldSetDescription"

    # Note Actions
    ADD_NOTE = "addNote"
    ADD_NOTES = "addNotes"
    CAN_ADD_NOTES = "canAddNotes"
    CAN_ADD_NOTES_WITH_ERROR_DETAIL = "canAddNotesWithErrorDetail"
    UPDATE_NOTE_FIELDS = "updateNoteFields"
    UPDATE_NOTE = "updateNote"
    UPDATE_NOTE_MODEL = "updateNoteModel"
    UPDATE_NOTE_TAGS = "updateNoteTags"
    GET_NOTE_TAGS = "getNoteTags"
    ADD_TAGS = "addTags"
    REMOVE_TAGS = "removeTags"
    GET_TAGS = "getTags"
    CLEAR_UNUSED_TAGS = "clearUnusedTags"
    REPLACE_TAGS = "replaceTags"
    REPLACE_TAGS_IN_ALL_NOTES = "replaceTagsInAllNotes"
    FIND_NOTES = "findNotes"
    GET_NOTES_INFO = "notesInfo"
    GET_NOTES_MOD_TIME = "notesModTime"
    DELETE_NOTES = "deleteNotes"
    REMOVE_EMPTY_NOTES = "removeEmptyNotes"

    # Statistic Actions
    GET_NUM_CARDS_REVIEWED_TODAY = "getNumCardsReviewedToday"
    GET_NUM_CARDS_REVIEWED_BY_DAY = "getNumCardsReviewedByDay"
    GET_COLLECTION_STATS_HTML = "getCollectionStatsHTML"
    GET_CARD_REVIEWS = "cardReviews"
    GET_REVIEWS_OF_CARDS = "getReviewsOfCards"
    GET_LATEST_REVIEW_ID = "getLatestReviewID"
    INSERT_REVIEWS = "insertReviews"

    API_MAP = {
        GET_CARDS: "findCards",
        GET_CARDS_EASE_FACTORS: "getEaseFactors",
        GET_CARDS_INTERVALS: "getIntervals",
        GET_CARDS_SUSPENDED_STATUS: "areSuspended",
        GET_CARDS_DUE_STATUS: "areDue",
        GET_CARDS_INFO: "cardsInfo",
        GET_CARDS_MOD_TIME: "cardsModTime",

        SET_EASE_FACTORS: "setEaseFactors",
        SET_SPECIFIC_VALUE_OF_CARD: "setSpecificValueOfCard",
        SUSPEND_CARD: "suspend",
        UNSUSPEND_CARD: "unsuspend",
        ANSWER_CARDS: "answerCards",
        FORGET_CARDS: "forgetCards",
        RELEARN_CARDS: "relearnCards",
        SYNC_CARDS: "syncCards",

        GET_DECK_NAMES: "deckNames",
        GET_DECK_NAMES_AND_IDS: "deckNamesAndIds",
        GET_DECKS_FOR_CARDS: "getDecks",
        GET_DECK_CONFIG: "getDeckConfig",
        GET_DECK_STATS: "getDeckStats",

        CREATE_DECK: "createDeck",
        CHANGE_DECK: "changeDeck",
        DELETE_DECKS: "deleteDecks",
        SAVE_DECK_CONFIG: "saveDeckConfig",
        SET_DECK_CONFIG_ID: "setDeckConfigId",
        CLONE_DECK_CONFIG_ID: "cloneDeckConfigId",
        REMOVE_DECK_CONFIG_ID: "removeDeckConfigId",

        GUI_BROWSE: "guiBrowse",
        GUI_SELECT_NOTE: "guiSelectNote",
        GUI_SELECTED_NOTES: "guiSelectedNotes",
        GUI_ADD_CARDS: "guiAddCards",
        GUI_EDIT_NOTE: "guiEditNote",
        GUI_CURRENT_CARD: "guiCurrentCard",
        GUI_START_CARD_TIMER: "guiStartCardTimer",
        GUI_SHOW_QUESTION: "guiShowQuestion",
        GUI_SHOW_ANSWER: "guiShowAnswer",
        GUI_ANSWER_CARD: "guiAnswerCard",
        GUI_UNDO: "guiUndo",
        GUI_DECK_OVERVIEW: "guiDeckOverview",
        GUI_DECK_BROWSER: "guiDeckBrowser",
        GUI_DECK_REVIEW: "guiDeckReview",
        GUI_IMPORT_FILE: "guiImportFile",
        GUI_EXIT_ANKI: "guiExitAnki",

        ADD_NOTE: "addNote",
        ADD_NOTES: "addNotes",
        CAN_ADD_NOTES: "canAddNotes",
        CAN_ADD_NOTES_WITH_ERROR_DETAIL: "canAddNotesWithErrorDetail",
        UPDATE_NOTE_FIELDS: "updateNoteFields",
        UPDATE_NOTE: "updateNote",
        UPDATE_NOTE_MODEL: "updateNoteModel",
        UPDATE_NOTE_TAGS: "updateNoteTags",
        GET_NOTE_TAGS: "getNoteTags",
        ADD_TAGS: "addTags",
        REMOVE_TAGS: "removeTags",
        GET_TAGS: "getTags",
        CLEAR_UNUSED_TAGS: "clearUnusedTags",
        REPLACE_TAGS: "replaceTags",
        REPLACE_TAGS_IN_ALL_NOTES: "replaceTagsInAllNotes",
        FIND_NOTES: "findNotes",
        GET_NOTES_INFO: "notesInfo",
        GET_NOTES_MOD_TIME: "notesModTime",
        DELETE_NOTES: "deleteNotes",
        REMOVE_EMPTY_NOTES: "removeEmptyNotes",

        GET_NUM_CARDS_REVIEWED_TODAY: "getNumCardsReviewedToday",
        GET_NUM_CARDS_REVIEWED_BY_DAY: "getNumCardsReviewedByDay",
        GET_COLLECTION_STATS_HTML: "getCollectionStatsHTML",
        GET_CARD_REVIEWS: "cardReviews",
        GET_REVIEWS_OF_CARDS: "getReviewsOfCards",
        GET_LATEST_REVIEW_ID: "getLatestReviewID",
        INSERT_REVIEWS: "insertReviews"
    }