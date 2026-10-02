"""Voting records for any assembly or parliament.

Nothing in this package is specific to the UN. The database schema, the models and
the lookup logic work the same for, say, the US Senate. Everything source-specific
lives in `unspeaks.sources` (one loader per data source) and is stored as data:
body descriptions, vote meanings, citations and extra details.

Words used throughout:
- body:     the assembly that voted ("UNGA", "UNSC", later e.g. "US-SENATE")
- decision: one thing that was decided (a resolution, a bill, a roll call)
- member:   who voted (a Member State, a senator), with a code and a name
- vote:     yes / no / abstain / present / not_voting
"""
