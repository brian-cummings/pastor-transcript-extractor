"""Analysis CLI adapters grouped by analytical capability.

Register the frozen content commands before their read-only design extension.
This preserves fingerprint-pinned execution adapters and the root CLI bytes.
"""
from pastor_transcript_extractor.commands.analysis import content as _content
from pastor_transcript_extractor.commands.analysis import context_design as _context_design
