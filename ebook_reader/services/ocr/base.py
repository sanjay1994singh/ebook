from dataclasses import asdict, dataclass, field
from typing import Protocol


DEVANAGARI_DIGIT_MAP = str.maketrans(
    {
        "\u0966": "0",
        "\u0967": "1",
        "\u0968": "2",
        "\u0969": "3",
        "\u096a": "4",
        "\u096b": "5",
        "\u096c": "6",
        "\u096d": "7",
        "\u096e": "8",
        "\u096f": "9",
    }
)


@dataclass(frozen=True)
class OcrWord:
    text: str
    normalized_text: str
    confidence: float | None
    left: int
    top: int
    width: int
    height: int
    block_num: int | None = None
    line_num: int | None = None
    par_num: int | None = None
    word_num: int | None = None

    def as_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class OcrResult:
    full_text: str
    normalized_text: str
    words: list[OcrWord] = field(default_factory=list)
    engine_name: str = ""
    languages: str = ""
    warnings: list[str] = field(default_factory=list)

    def as_dict(self):
        return asdict(self)


class OcrEngine(Protocol):
    engine_name: str

    def extract(self, image) -> OcrResult:
        raise NotImplementedError


def normalize_devanagari_digits(text):
    return (text or "").translate(DEVANAGARI_DIGIT_MAP)
