"""Analysis CLI adapters grouped by analytical capability.

Register the frozen content commands before their read-only design extension.
This preserves fingerprint-pinned execution adapters and the root CLI bytes.
"""
from pastor_transcript_extractor.commands.analysis import content as _content
from pastor_transcript_extractor.commands.analysis import context_design as _context_design
from pastor_transcript_extractor.commands.analysis import learning as _learning
from pastor_transcript_extractor.commands.analysis import profile_support as _profile_support
from pastor_transcript_extractor.commands.analysis import bound_claims as _bound_claims
from pastor_transcript_extractor.commands.analysis import object_position as _object_position
from pastor_transcript_extractor.commands.analysis import thought_units as _thought_units
from pastor_transcript_extractor.commands.analysis import pastor_fit as _pastor_fit
from pastor_transcript_extractor.commands.analysis import benchmark_explainer as _benchmark_explainer
from pastor_transcript_extractor.commands.analysis import church_fit as _church_fit
