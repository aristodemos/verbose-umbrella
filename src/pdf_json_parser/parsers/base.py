from abc import ABC, abstractmethod
from pathlib import Path

from pdf_json_parser.parsers.types import ParsedDocument



class BaseParser(ABC):
    name: str
    
    @abstractmethod
    def parse(self, pdf_path: Path) -> ParsedDocument:
        """Parse a PDF file and return a ParsedDocument object."""
        raise NotImplementedError("Subclasses must implement the parse method.")
    
    