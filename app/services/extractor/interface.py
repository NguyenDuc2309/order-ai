from abc import ABC, abstractmethod

from app.models.extraction import ExtractionResult


class BaseExtractor(ABC):
    @abstractmethod
    def extract(self, query: str) -> ExtractionResult:
        raise NotImplementedError
