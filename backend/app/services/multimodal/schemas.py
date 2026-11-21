from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class MultimodalAsset:
    asset_type: str
    object_name: str
    mime_type: str | None = None
    size_bytes: int = 0
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MultimodalSegment:
    segment_id: str
    text: str
    modality: str
    start_seconds: float = -1.0
    end_seconds: float = -1.0
    page_number: int = -1
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MultimodalDocument:
    source_id: str
    modality: str
    text: str
    source_uri: str
    assets: list[MultimodalAsset] = field(
        default_factory=list
    )
    segments: list[MultimodalSegment] = field(
        default_factory=list
    )
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "modality": self.modality,
            "text": self.text,
            "source_uri": self.source_uri,
            "assets": [
                asset.to_dict()
                for asset in self.assets
            ],
            "segments": [
                segment.to_dict()
                for segment in self.segments
            ],
            "metadata": self.metadata,
        }


def build_multimodal_document(
    *,
    source_id: str,
    modality: str,
    source_uri: str,
    parsed_units: list[Any],
    assets: list[MultimodalAsset] | None = None,
    metadata: dict[str, Any] | None = None,
) -> MultimodalDocument:
    segments: list[MultimodalSegment] = []

    for index, unit in enumerate(parsed_units):
        unit_metadata = dict(
            getattr(unit, "metadata", {})
            or {}
        )

        segments.append(
            MultimodalSegment(
                segment_id=(
                    f"{source_id}:{index}"
                ),
                text=unit.text,
                modality=unit_metadata.get(
                    "media_type",
                    modality,
                ),
                start_seconds=float(
                    unit_metadata.get(
                        "start_seconds",
                        -1.0,
                    )
                ),
                end_seconds=float(
                    unit_metadata.get(
                        "end_seconds",
                        -1.0,
                    )
                ),
                page_number=int(
                    getattr(
                        unit,
                        "page_number",
                        -1,
                    )
                ),
                metadata=unit_metadata,
            )
        )

    text = "\n\n".join(
        segment.text
        for segment in segments
        if segment.text.strip()
    )

    return MultimodalDocument(
        source_id=source_id,
        modality=modality,
        text=text,
        source_uri=source_uri,
        assets=assets or [],
        segments=segments,
        metadata=metadata or {},
    )