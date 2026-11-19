"""Store source observations locally and turn selected captures into research reports.

raw_captures writes native JSON before database loading. database and amsterdam manage the
USD quote and EUR trade schemas respectively. reporting writes reusable CSV and JSON
outputs, while status reads SQL table previews for the U.S. market and synthetic datasets.
"""
