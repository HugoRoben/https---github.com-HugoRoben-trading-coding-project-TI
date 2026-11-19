"""Read delayed Amsterdam share and option executions for the research pipeline.

The retrieval module combines Euronext trade publications with ESMA contract records. The
observations module reconciles publications by trade ID and finds a share price observable
when each option traded. Storage and EUR scenario valuation are handled by
modules.storage_reporting.amsterdam.
"""
