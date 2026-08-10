"""Qt-free public API for BDO Music Composer SDK integrations.

Import this concrete module when embedding the codec, MIDI transforms, editor
model, or export helpers.  The package initializer intentionally stays inert.
"""

from __future__ import annotations

from bdo_codec import (
    BDO_VERSION,
    MAX_NOTES_PER_TRACK,
    BdoCodecError,
    BdoDecodeError,
    BdoDocument,
    BdoEncodeError,
    BdoHeader,
    BdoInstrumentGroup,
    BdoNote,
    BdoTrack,
    BdoTrackSettings,
    CodecDiffEntry,
    CodecIssue,
    UnsafeOpaqueDataError,
    build_plaintext,
    compare_score_documents,
    decode_score,
    document_from_dict,
    document_to_dict,
    encode_score,
    read_score,
    score_instrument_ids,
    validate_score,
    write_score,
)
from bdo_common.bdo_track_effects import (
    DEFAULT_TRACK_VOLUME,
    MasterEffects,
    TrackEffectSends,
    decode_track_effects,
    encode_track_effects,
    track_volume_preview_gain,
)
from bdo_export import (
    BDO_BPM_MAX,
    BDO_BPM_MIN,
    MAX_NOTES_PER_INSTRUMENT,
    bind_dual_velocities,
    build_score_document,
    channel_groups_to_bdo,
    document_matches_logical_tracks,
    make_track_settings,
    score_summary,
    split_notes,
)
from bdo_midi import (
    BDO_INSTRUMENT_NAMES,
    BDO_INSTRUMENTS,
    BDO_NOTE_MAX,
    BDO_NOTE_MIN,
    BDO_VEL_LEVELS,
    ChannelGroup,
    Note,
    clamp_notes,
    floor_velocity,
    gm_program_name,
    gm_to_bdo_instrument,
    instrument_supports_composer_effects,
    layered_velocity,
    map_drum_notes,
    normalize_drum_note_timing,
    parse_midi,
    performance_instrument_id,
    rescale_velocity,
    stepped_velocity,
    transpose_notes,
)
from bdo_music_composer.app.application_metadata import APP_NAME, APP_VERSION
from bdo_music_composer.editor.bdo_semantic_diagnostics import (
    SemanticDiagnostic,
    SemanticDiff,
    diagnose_bdo_authoring,
    semantic_diff,
    semantic_readiness_score,
)
from bdo_music_composer.editor.editor_models import TrackState
from bdo_common.extension_contract import (
    ExtensionRequirement,
    HostExtensionContract,
    NegotiatedExtension,
    negotiate_extension,
)


SDK_API_VERSION = 1
SDK_CAPABILITIES = frozenset({
    "codec.read",
    "codec.write",
    "midi.parse",
    "model.snapshot",
    "score.build",
    "semantic.diagnostics",
})
SDK_HOST_CONTRACT = HostExtensionContract(
    "bdo.sdk",
    SDK_API_VERSION,
    SDK_CAPABILITIES,
    frozenset({"python-api"}),
)


def negotiate_sdk_extension(
    requirement: ExtensionRequirement,
) -> NegotiatedExtension:
    return negotiate_extension(SDK_HOST_CONTRACT, requirement)


__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "BDO_BPM_MAX",
    "BDO_BPM_MIN",
    "BDO_INSTRUMENT_NAMES",
    "BDO_INSTRUMENTS",
    "BDO_NOTE_MAX",
    "BDO_NOTE_MIN",
    "BDO_VEL_LEVELS",
    "BDO_VERSION",
    "DEFAULT_TRACK_VOLUME",
    "MAX_NOTES_PER_INSTRUMENT",
    "MAX_NOTES_PER_TRACK",
    "SDK_API_VERSION",
    "SDK_CAPABILITIES",
    "SDK_HOST_CONTRACT",
    "SemanticDiagnostic",
    "SemanticDiff",
    "BdoCodecError",
    "BdoDecodeError",
    "BdoDocument",
    "BdoEncodeError",
    "BdoHeader",
    "BdoInstrumentGroup",
    "BdoNote",
    "BdoTrack",
    "BdoTrackSettings",
    "ChannelGroup",
    "CodecDiffEntry",
    "CodecIssue",
    "MasterEffects",
    "Note",
    "TrackEffectSends",
    "TrackState",
    "UnsafeOpaqueDataError",
    "bind_dual_velocities",
    "build_plaintext",
    "build_score_document",
    "channel_groups_to_bdo",
    "clamp_notes",
    "compare_score_documents",
    "decode_score",
    "decode_track_effects",
    "diagnose_bdo_authoring",
    "document_from_dict",
    "document_matches_logical_tracks",
    "document_to_dict",
    "encode_score",
    "encode_track_effects",
    "floor_velocity",
    "gm_program_name",
    "gm_to_bdo_instrument",
    "instrument_supports_composer_effects",
    "layered_velocity",
    "make_track_settings",
    "map_drum_notes",
    "normalize_drum_note_timing",
    "negotiate_sdk_extension",
    "parse_midi",
    "performance_instrument_id",
    "read_score",
    "rescale_velocity",
    "score_instrument_ids",
    "score_summary",
    "semantic_diff",
    "semantic_readiness_score",
    "split_notes",
    "stepped_velocity",
    "track_volume_preview_gain",
    "transpose_notes",
    "validate_score",
    "write_score",
]
