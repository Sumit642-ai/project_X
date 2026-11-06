"""AI note draft for the Live pane.

The model only drafts text for the nurse's free-text note. Every sentence must cite transcript
turns; uncited sentences are shown struck through as UNSUPPORTED, and medication names found in
neither the transcript nor the member's Facts are flagged. The write-back mapping refuses AI text
anywhere but the note body (app/writeback/mapping.py), whatever the UI does.
"""
