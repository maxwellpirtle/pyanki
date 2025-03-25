from dataclasses import dataclass, field
from dataclasses_json import dataclass_json
from typing import List
from pathlib import Path

@dataclass_json
@dataclass
class Resource:
    # The name of the file as it will appear in the Anki database
    filename: Path
    skip_hash: str

    def get_schema(self):
        return Resource.schema()

    @staticmethod
    def dump(resources):
        return [resource.get_schema().dump(resource) for resource in resources]

@dataclass_json
@dataclass
class FileResource(Resource):
    path: Path
    skip_hash: str

    def get_schema(self):
        return FileResource.schema()

@dataclass_json
@dataclass
class URLResource(Resource):
    path: str

    def get_schema(self):
        return URLResource.schema()

@dataclass_json
@dataclass
class DataResource(Resource):
    data: bytes

    def get_schema(self):
        return DataResource.schema()

@dataclass
class FieldContent:
    text: str
    images: List[Resource] = field(default_factory=list)
    audio: List[Resource] = field(default_factory=list)
    video: List[Resource] = field(default_factory=list)

    def __str__(self):
        return self.text