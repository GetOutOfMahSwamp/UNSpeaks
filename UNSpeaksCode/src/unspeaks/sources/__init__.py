"""Loaders that turn a data source into the generic voting database.

One module per source. To add, say, the US Senate, write `us_senate.py` with a
`load(writer, raw_dir, log)` function that adds its body, sources, decisions and
votes, and call it from `unspeaks.build_db`.
"""
