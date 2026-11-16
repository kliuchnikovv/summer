"""ParserType -> Parser instance. Adding a parser is a one-line change here."""
from __future__ import annotations

from app.application.ports import Parser
from app.domain.models import ParserType
from app.infrastructure.parsers.gemini_parser import GeminiParser
from app.infrastructure.parsers.openai_parser import OpenAIOCRParser
from app.infrastructure.parsers.pypdf_parser import PyPDFParser


class ParserRegistryImpl:
    def __init__(self) -> None:
        self._registry: dict[ParserType, Parser] = {
            ParserType.PYPDF: PyPDFParser(),
            ParserType.GEMINI: GeminiParser(),
            ParserType.OPENAI: OpenAIOCRParser(),
        }

    def get(self, parser: ParserType) -> Parser:
        return self._registry[parser]
