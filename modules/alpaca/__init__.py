"""Collect U.S. stock and option quotes for the local research database.

Start with retrieval.iter_captures for a collection session. The client module builds the
authenticated GET requests. Normalization converts the resulting dictionaries into shared
contract and quote records, including missing fields the quality checks need to see.
"""
