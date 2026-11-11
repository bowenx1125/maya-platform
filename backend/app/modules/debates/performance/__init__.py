"""Debate performance compiler: animation timelines for the 3D stage."""

from app.modules.debates.performance.compiler import (
    EMOTIONS,
    GESTURE_DUR,
    POSTURES,
    CompiledPerformance,
    PerformanceEvent,
    compile_performance,
    estimate_duration,
    rule_based_performance,
    validate_performance,
)
from app.modules.debates.performance.visemes import (
    VisemeWindow,
    anchor_to_time,
    assemble_viseme_windows,
    char_to_viseme,
    flatten_sentences,
    syllable_to_viseme,
)

__all__ = [
    "EMOTIONS",
    "GESTURE_DUR",
    "POSTURES",
    "CompiledPerformance",
    "PerformanceEvent",
    "VisemeWindow",
    "anchor_to_time",
    "assemble_viseme_windows",
    "char_to_viseme",
    "compile_performance",
    "estimate_duration",
    "flatten_sentences",
    "rule_based_performance",
    "syllable_to_viseme",
    "validate_performance",
]
