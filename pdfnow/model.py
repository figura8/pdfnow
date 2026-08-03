"""Document model — the single source of truth for all operations.

Every operation (OCR, correction, export) reads and writes this model.
The model is serializable to JSON so projects can be saved and resumed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional
import json


class BlockType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    TABLE = "table"
    STAMP = "stamp"
    SIGNATURE = "signature"
    UNKNOWN = "unknown"


class CorrectionStatus(str, Enum):
    UNTOUCHED = "untouched"       # OCR output, not reviewed
    CORRECTED = "corrected"       # User has edited this
    CONFIRMED = "confirmed"       # User says this is correct
    LOCKED = "locked"             # Must not be changed (names, dates, etc.)


@dataclass
class BBox:
    """Axis-aligned bounding box in page coordinates (origin: top-left)."""
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def area(self) -> float:
        return self.width * self.height

    def overlap_ratio(self, other: BBox) -> float:
        """IoU-style overlap ratio with another bbox."""
        ox0 = max(self.x0, other.x0)
        oy0 = max(self.y0, other.y0)
        ox1 = min(self.x1, other.x1)
        oy1 = min(self.y1, other.y1)
        if ox0 >= ox1 or oy0 >= oy1:
            return 0.0
        inter = (ox1 - ox0) * (oy1 - oy0)
        return inter / min(self.area, other.area)

    def to_dict(self) -> dict:
        return {"x0": self.x0, "y0": self.y0, "x1": self.x1, "y1": self.y1}

    @classmethod
    def from_dict(cls, d: dict) -> BBox:

        return cls(x0=d["x0"], y0=d["y0"], x1=d["x1"], y1=d["y1"])


@dataclass
class Word:
    """Single word with its bounding box and OCR confidence."""
    text: str
    bbox: BBox
    confidence: float          # 0.0 – 1.0
    corrected_text: str | None = None
    status: CorrectionStatus = CorrectionStatus.UNTOUCHED

    @property
    def display_text(self) -> str:
        """The text to show: corrected if available, otherwise OCR."""
        return self.corrected_text if self.corrected_text is not None else self.text

    @property
    def is_low_confidence(self) -> bool:
        return self.confidence < 0.6

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "bbox": self.bbox.to_dict(),
            "confidence": self.confidence,
            "corrected_text": self.corrected_text,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Word:
        return cls(
            text=d["text"],
            bbox=BBox.from_dict(d["bbox"]),
            confidence=d["confidence"],
            corrected_text=d.get("corrected_text"),
            status=CorrectionStatus(d.get("status", "untouched")),
        )


@dataclass
class Line:
    """A line of text composed of words."""
    words: list[Word]

    @property
    def bbox(self) -> BBox:
        if not self.words:
            return BBox(0, 0, 0, 0)
        return BBox(
            x0=min(w.bbox.x0 for w in self.words),
            y0=min(w.bbox.y0 for w in self.words),
            x1=max(w.bbox.x1 for w in self.words),
            y1=max(w.bbox.y1 for w in self.words),
        )

    @property
    def text(self) -> str:
        return " ".join(w.display_text for w in self.words)

    @property
    def avg_confidence(self) -> float:
        if not self.words:
            return 1.0
        return sum(w.confidence for w in self.words) / len(self.words)

    def to_dict(self) -> dict:
        return {"words": [w.to_dict() for w in self.words]}

    @classmethod
    def from_dict(cls, d: dict) -> Line:
        return cls(words=[Word.from_dict(w) for w in d["words"]])


@dataclass
class Block:
    """A visual block: could be text, image, table, stamp, etc."""
    bbox: BBox
    lines: list[Line] = field(default_factory=list)
    block_type: BlockType = BlockType.TEXT
    label: str = ""            # e.g. "header", "body", "footer"
    replacement_text: str | None = None  # if set, replaces all line text in export
    deleted: bool = False                # if True, block is excluded from export

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def avg_confidence(self) -> float:
        if not self.lines:
            return 1.0
        confs = [line.avg_confidence for line in self.lines]
        return sum(confs) / len(confs)

    def to_dict(self) -> dict:
        d = {
            "bbox": self.bbox.to_dict(),
            "lines": [l.to_dict() for l in self.lines],
            "block_type": self.block_type.value,
            "label": self.label,
        }
        if self.replacement_text is not None:
            d["replacement_text"] = self.replacement_text
        if self.deleted:
            d["deleted"] = True
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Block:
        return cls(
            bbox=BBox.from_dict(d["bbox"]),
            lines=[Line.from_dict(l) for l in d.get("lines", [])],
            block_type=BlockType(d.get("block_type", "text")),
            label=d.get("label", ""),
            replacement_text=d.get("replacement_text"),
            deleted=d.get("deleted", False),
        )


@dataclass
class Page:
    """A single page of the document."""
    number: int
    image_path: str | None = None          # path to extracted page image
    width: float = 0.0
    height: float = 0.0
    blocks: list[Block] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(block.text for block in self.blocks)

    @property
    def word_count(self) -> int:
        return sum(len(line.words) for block in self.blocks for line in block.lines)

    @property
    def low_confidence_count(self) -> int:
        return sum(
            1 for block in self.blocks
            for line in block.lines
            for word in line.words
            if word.is_low_confidence
        )

    def to_dict(self) -> dict:
        return {
            "number": self.number,
            "image_path": self.image_path,
            "width": self.width,
            "height": self.height,
            "blocks": [b.to_dict() for b in self.blocks],
        }

    @classmethod
    def from_dict(cls, d: dict) -> Page:
        return cls(
            number=d["number"],
            image_path=d.get("image_path"),
            width=d.get("width", 0.0),
            height=d.get("height", 0.0),
            blocks=[Block.from_dict(b) for b in d.get("blocks", [])],
        )


@dataclass
class Document:
    """The complete document model."""
    source_path: str
    pages: list[Page] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def total_words(self) -> int:
        return sum(p.word_count for p in self.pages)

    @property
    def low_confidence_words(self) -> int:
        return sum(p.low_confidence_count for p in self.pages)

    @property
    def overall_confidence(self) -> float:
        total = self.total_words
        if total == 0:
            return 1.0
        return 1.0 - (self.low_confidence_words / total)

    def to_dict(self) -> dict:
        return {
            "source_path": self.source_path,
            "metadata": self.metadata,
            "pages": [p.to_dict() for p in self.pages],
        }

    @classmethod
    def from_dict(cls, d: dict) -> Document:
        return cls(
            source_path=d["source_path"],
            metadata=d.get("metadata", {}),
            pages=[Page.from_dict(p) for p in d.get("pages", [])],
        )

    def save(self, path: str | Path) -> None:
        """Serialize document to JSON."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> Document:
        """Deserialize document from JSON."""
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
