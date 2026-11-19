"""Group the implementations used by the local options research pipeline.

The provider packages retrieve and decode exchange or broker data. The models package
consumes observations for pricing and synthetic replay. The storage_reporting package owns
raw archives, SQLite tables and report files. The command-line entry point and shared
domain records live in options_lab.
"""
