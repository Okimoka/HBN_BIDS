# Repair reference data

`event_columns.json` contains the supported behavioral column definitions from
the published R1 dictionaries, with the A02 contrast correction and A06 removal
of unsupported feedback HED. A03 uses these for missing definitions; it does
not create new behavioral measurements.

`behavior_review.tsv` records the earlier inspection of 26,672 event files.
It contains 298 original A10 flags, 100 A11 answer-association flags, 12 A12
behavioral-disagreement flags and 15 A13 movie-marker findings, alongside
coverage and source hashes. A10 also
has a broader live marker screen; A13 additionally checks movie anchors; A14
checks event duration against the signal extent. The repair checks the event
hash and, for A11–A13, the behavioral-file hash before using an entry.
`absent` means the specified inspection found no listed issue, not that all scientific properties passed.

The [project report](../../report/report.pdf) describes the November 2026
comparison snapshot and its limits. Source hashes are in `behavior_review.tsv`;
the original audit scripts are working research material outside the published
repository. The table is reference data rather than a replacement behavioral parser.
Changed/new source files need a new comparison; the tool reports unknown
instead of silently reusing an old conclusion.

`quality_columns.json` defines the published table's fields and recommendation categories.
Keep this whole `data/` directory when copying `hbn_repair` elsewhere.
