import itertools

from dataclasses import dataclass, field
from anki.scope import DuplicateScope, DuplicateScopeOptions
from anki.resource import FieldContent, Resource
from typing import List

@dataclass
class Note:
    """
    :param deck_name: The name of the deck where the note will be added.
    :param model_name: The name of the model to use for the note.
    :param options: An optional DuplicateScopeOptions for note creation
    :param field_content: A dictionary containing the field names and their corresponding values.
    :param tags: An optional list of tags to associate with the note
    """
    deck_name: str
    model_name: str
    options: DuplicateScopeOptions
    field_content: dict[str, FieldContent] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)

    def __getattr__(self, item):
        return self.field_content[item]

    @staticmethod
    def make_basic_card(deck_name: str, front: str, back: str, examples: str, images: List[Resource] = None, tags: List[str] = None):
        return Note(
            deck_name=deck_name,
            model_name='Basic',
            field_content=
            {
                "Front": FieldContent(text=front),
                "Back": FieldContent(text=back),
                "Image": FieldContent(text='', images=images if images else []),
                "Examples": FieldContent(text=examples),
            },
            tags=tags or [],
            options=DuplicateScopeOptions.default(deck_name),
        )

    def to_anki_params(self):
        # NOTE: This does not elegantly handle the case where
        # two "equivalent" objects are used in two different fields
        # with two different items. That is, if the
        #
        # field_contents = {
        #    'Front' : ('Front text', Resource A),
        #    'Back' : ('Back text', Resource A)
        # }
        #
        # Then two instances of resource A will appear instead of
        # a single instance which points at both `Front` and `Back`.
        #
        # Since the AnkiAPI should be able to handle this case,
        # we ignore simplification for now.
        audio_content = []
        video_content = []
        image_content = []
        text_content = {}
        options_content = DuplicateScopeOptions.schema().dump(self.options)
        for field_name, content in self.field_content.items():
            text_content[field_name] = content.text
            new_audio_content = Resource.dump(content.audio)
            new_video_content = Resource.dump(content.video)
            new_image_content = Resource.dump(content.images)
            for new_content in itertools.chain(new_audio_content, new_video_content, new_image_content):
                new_content['fields'] = [field_name]
            if new_audio_content:
                audio_content += new_audio_content
            if new_audio_content:
                video_content += new_video_content
            if new_image_content:
                image_content += new_image_content

        return {
            "deckName": self.deck_name,
            "modelName": self.model_name,
            "fields": text_content,
            "tags": self.tags,
            "options": options_content,
            "audio": audio_content,
            "video": video_content,
            "picture": image_content,
        }