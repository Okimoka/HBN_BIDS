#set document(title: "An update proposal to the HBN-EEG datasets", author: "Okan Mazlum", date: datetime(year: 2026, month: 11, day: 21))
#set page(numbering: "1")
#show heading: set text(size: 1.2em)
#show link: it => text(fill: rgb("1b5e9e"), underline(it))

#let fair = "https://www.biorxiv.org/content/10.1101/2024.10.03.615261v2"
#let physio = "https://bids-specification.readthedocs.io/en/v1.11.2/modality-specific-files/physiological-recordings.html#eye-tracking"
#let bids-events = "https://bids-specification.readthedocs.io/en/v1.11.2/modality-agnostic-files/events.html"
#let bids-behavior = "https://bids-specification.readthedocs.io/en/v1.11.2/modality-specific-files/behavioral-experiments.html"
#let smi-manual = "https://psychologie.unibas.ch/fileadmin/user_upload/psychologie/Forschung/N-Lab/SMI_BeGaze_Manual.pdf"

// excerpts retain source values; highlights identify relevant lines and grey markers show omissions
#let excerpt(lines, marked: (), headers: ()) = block(width: 100%, inset: 4pt, stroke: 0.3pt + luma(80%))[
  #show raw: set text(font: "DejaVu Sans Mono", size: 8pt)
  #set par(leading: 2pt)
  #for (index, line) in lines.enumerate() {
    block(above: 0pt, below: 0pt, inset: (top: 1.5pt, bottom: 1.5pt), fill: if index in marked { rgb("fff0c2") } else { none })[
      #text(weight: if index in headers { "bold" } else { "regular" }, fill: if line.starts-with("… (") { luma(55%) } else { black }, raw(line, block: true))
    ]
  }
]

#let comparison(before, after, columns: (1fr, 1fr), left: [HBN-EEG .tsv], right: [Proposed .tsv]) = block(breakable: false)[
  #grid(columns: columns, gutter: 10pt,
    [#strong(left) #v(3pt) #before],
    [#strong(right) #v(3pt) #after],
  )
]

#let example(file) = block(sticky: true)[*Example: #raw(file)*]

#title()

= Introduction

The HBN-EEG datasets (#link(fair)[Shirazi et al.]) make the original Healthy Brain Network (HBN) EEG recordings available in the Brain Imaging Data Structure (BIDS). This conversion also incorporates selected behavioral information and event descriptions from the original HBN dataset. The proposed update builds on that resource through four contributions: repairing the existing EEG releases, adding further behavioral information, integrating eye tracking, and providing clearer recording-level quality information.

This report describes the changes, their evidence and their implementation. Corrections and additions preserve existing recording identities wherever possible, aiming for compatibility with existing workflows. Installation and usage are documented in the repository READMEs.

== Project architecture

#image("figures/architecture.svg", width: 100%) <architecture>

Program modules shown in blue: `download_dataset` retrieves the inputs, `hbn_repair` repairs the existing releases, and `hbn_augment` adds ET through `smi2bids` as well as additional behavioral information. `hbn_bundle` optionally combines the release outputs for easier analysis.

=== Output layout and supporting files

The collection contains 3,155 participants and 26,672 HBN-EEG recordings across R1–R11 with tasks resting state, movies, contrast change, surround suppression, symbol search and sequence learning. HBN-EEG comes from NEMAR, original ET and behavioral exports come from S3. The inspections also consulted original S3 EEG exports to establish where discrepancies originated.

#pagebreak()
= Addressed issues

Disclaimer: These issues were discovered through extended work with the dataset, using the #link("https://bids-validator.readthedocs.io/en/latest/")[BIDS Validator], and letting LLMs search for potential problems. Some issues potentially remain.

The issues are named based on which part of the process they adress: *`A`* identifies repairs of the original HBN-EEG releases and retained limitations; *`B`* identifies behavioral additions; *`C`* identifies ET integration.

== A. Repair of the HBN-EEG releases

#text(size: 9pt)[#table(columns: (0.5fr, 2.65fr, 0.8fr, 1fr), inset: 4pt,
  table.header([*Issue*], [*Problem*], [*Origin*], [*Subjects*]),
  [#link(<a01>)[A01]], [Event labels in `*_events.tsv` / `.set` can describe the wrong task; some first TSV labels differ from `.set`], [HBN-EEG], [225],
  [#link(<a02>)[A02]], [Contrast descriptions in `*_events.json` say 0.33/0.66 while TSV values are 0.3/0.6], [HBN-EEG], [1,844],
  [#link(<a03>)[A03]], [Existing `*_events.tsv` columns/categories lack definitions in `*_events.json`], [HBN-EEG], [All],
  [#link(<a04>)[A04]], [Time-unit labels in `*_events.json` use `seconds` instead of `s`], [HBN-EEG], [All],
  [#link(<a05>)[A05]], [The dataset-source key in `dataset_description.json` is misspelled as `SourceDatesets`], [HBN-EEG], [All],
  [#link(<a06>)[A06]], [Contrast feedback uses the wrong row; sequence-learning dot identities and initial OFF events have incorrect HED annotations], [HBN-EEG], [2,191],
  [#link(<a07>)[A07]], [Channel types/units are missing], [HBN-EEG], [963],
  [#link(<a08>)[A08]], [Channel counts and other acquisition metadata are missing], [HBN-EEG], [All],
  [#link(<a09>)[A09]], [S3/HBN-EEG inventory is lacking, `.tsv` files are comma-delimited], [HBN-EEG], [All],
)]

The following issues were not fixed, but instead logged in the quality tables.

#text(size: 9pt)[#table(columns: (0.5fr, 2.65fr, 0.8fr, 1fr), inset: 4pt,
  table.header([*Issue*], [*Problem*], [*Origin*], [*Subjects*]),
  [#link(<a10>)[A10]], [An EEG task recording can include another task or run], [S3 → HBN-EEG], [1,057],
  [#link(<a11>)[A11]], [
    In the symbol search task, unanswered symbol search rows make the answer-to-response associations uncertain
    ], [S3 → HBN-EEG], [100],
  [#link(<a12>)[A12]], [S3 trial values or planned block counts disagree with HBN-EEG events], [Unresolved - likely HBN-EEG], [12],
  [#link(<a13>)[A13]], [Movie start/stop markers disagree with expectations or are missing/repeated], [S3 → HBN-EEG], [89],
  [#link(<a14>)[A14]], [An event's onset plus duration extends beyond the signal], [HBN-EEG], [2],
  [#link(<a15>)[A15]], [Ten six-channel exports contain constants and test-like waveforms], [S3 → HBN-EEG], [2],
)]

#text(size: 9pt)[*Origin:* *HBN-EEG* identifies a conversion/metadata issue in those releases; *S3 → HBN-EEG* identifies a source irregularity retained in the release. *Unresolved* means the sources disagree but the erroneous source has not been established. Since S3 is the source data, it could be assumed that the error source is HBN-EEG]

The issues are illustrated in more detail below, including excerpts from actual files and their corrected versions. Excerpts only show the columns that are relevant to the example.

The following file trees show the four dataset stages represented by folded notes in the #link(<architecture>)[architecture diagram].

#block(breakable: false)[
#grid(columns: (1fr, 1fr), gutter: 16pt,
  [*HBN_RAW.* Downloaded HBN-EEG releases are under `EEG/R1`–`R11`; original ET and behavioral exports are grouped separately by participant.

  #image("figures/HBN_RAW.svg", width: 100%)],
  [*HBN_REPAIRED.* Releases retain their layout and participant files, with repaired metadata and recording-quality tables. ET and BEH link to the downloads.

  #image("figures/HBN_REPAIRED.svg", width: 100%)],
)
]

#block(breakable: false)[
#grid(columns: (1fr, 1fr), gutter: 16pt,
  [*HBN_AUGMENTED.* Repaired releases gain BIDS eye-tracking files for each exported eye where conversion succeeds.

  #image("figures/HBN_AUGMENTED.svg", width: 100%)],
  [*HBN_MERGED.* The optional analysis dataset links augmented EEG folders, scopes shared sidecars to participants, and combines participant and quality tables across all 11 releases.

  #image("figures/HBN_MERGED.svg", width: 100%)],
)
]

=== A01. Incorrect event labels <a01>

For mixed-task recordings (see A10), the `*_events.tsv` files can have incorrect event labels. This is because the same acquisition codes are reused across tasks. The repair uses the explicit task start markers to correct labels in both the TSV and the corresponding .set event variable (other columns remain unmodified).

#example("R3 — sub-NDARUX886JLM_task-seqLearning6target_events.tsv")

Note that only the event labels are incorrect, but they can be recovered from the event code in the context of the right task. 

#comparison(excerpt((
"onset   value                 event_code",
"… (77 rows skipped)",
"324.57  seqLearning_stop      50",
"326.616 break cnt             break cnt",
"368.104 symbolSearch_start    92",
"371.036 instructed_toOpenEyes 20",
"398.622 dot_no4_ON            14",
"401.26  dot_no4_ON            14",
"… (7 rows skipped)",
), marked: (5,6,7,), headers: (0,)), excerpt((
"onset   value                 event_code",
"… (77 rows skipped)",
"324.57  seqLearning_stop      50",
"326.616 break cnt             break cnt",
"368.104 symbolSearch_start    92",
"371.036 newPage               20",
"398.622 trialResponse         14",
"401.26  trialResponse         14",
"… (7 rows skipped)",
), marked: (5,6,7,), headers: (0,)))


In addition to this, there are 43 recordings where the event label of the first row was different between the `*_events.tsv` and `.set` files. In each case, the `_events.tsv` was updated to reflect the value seen in the `.set` file.

#example("R1 — sub-NDARAC904DMU_task-seqLearning8target_events.tsv")

#comparison(excerpt((
"onset   value             event_code",
"0       n/a               27",
"211.79  seqLearning_start 91",
"218.056 learningBlock_1   31",
), marked: (1,), headers: (0,)), excerpt((
"latency type              event_code",
"1       dot_no7_OFF       27",
"105896  seqLearning_start 91",
"109029  learningBlock_1   31",
), marked: (1,), headers: (0,)), right: [HBN-EEG .set, decoded])

=== A02. Correct contrast-category descriptions <a02>

Surround suppression `*_events.json` dictionaries describe categories `0.33`/`0.66`, although `*_events.tsv` measurements use `0.3`/`0.6`. The repair changes the JSON `Levels` and corresponding HED fractions.

#example("R9 — task-surroundSupp_events.json")

The excerpts show `foreground_contrast.Levels`.

#comparison(excerpt(("… (51 rows skipped)",
"    \"Levels\": {",
"      \"0\": \"No contrast\",",
"      \"0.33\": \"1/3 contrast\",",
"      \"0.66\": \"2/3 contrast\",",
"      \"1\": \"Full contrast\"",
"    },",
"… (29 rows skipped)",), marked: (3,4,)), excerpt(("… (51 rows skipped)",
"    \"Levels\": {",
"      \"0\": \"No contrast\",",
"      \"1\": \"Full contrast\",",
"      \"0.3\": \"Encoded foreground contrast 0.3\",",
"      \"0.6\": \"Encoded foreground contrast 0.6\"",
"    },",
"… (29 rows skipped)",), marked: (4,5,)), columns: (2fr, 3fr), left: [HBN-EEG .json], right: [Proposed .json])

=== A03. Describe existing columns and categories <a03>

Some columns or category values in `*_events.tsv` files lack definitions in the corresponding `*_events.json` files. The repair adds descriptions without changing measurements or creating event rows.
The existing TSV already contains these values (R10 NDARUZ062BWR, surround suppression run 1; selected stimulus rows and columns):

#block(sticky: true)[*HBN-EEG `_events.tsv`*]

This uses columns `background`, `foreground_contrast`, and `stimulus_cond`.

#excerpt((
"onset background foreground_contrast stimulus_cond",
"66.52 1          0                   2",
"72.37 1          0.3                 3",
), marked: (), headers: (0,))

#example("R10 — task-surroundSupp_events.json")

The HBN-EEG dictionary ends after five generic columns, and is missing the `background`, `foreground_contrast` and `stimulus_cond` columns that exist in the `_events.tsv`. The proposal only shows the added background description, the other two definitions are also added.

#comparison(excerpt(("… (19 rows skipped)",
"  \"event_code\": {",
"    \"Description\": \"The original code used\n  during data collection to indicate an\n  event marker.\",",
"    \"Levels\": {",
"      \"one\": \"place holder\"",
"    }",
"  }",
"}",), marked: ()), excerpt(("… (19 rows skipped)",
"  \"event_code\": {",
"    \"Description\": \"The original code used\n  during data collection to indicate an\n  event marker.\",",
"    \"Levels\": {",
"      \"one\": \"place holder\"",
"    }",
"  },",
"  \"background\": {",
"    \"Description\": \"Whether the background\n  is present\",",
"    \"Levels\": {",
"      \"0\": \"Background is not present\",",
"… (36 rows skipped)",), marked: (7,8,9,10,)), left: [HBN-EEG .json], right: [Proposed .json])


=== A04. Normalize time-unit labels <a04>

Shared `*_events.json` files use `Units: "seconds"`; the repair writes `Units: "s"`. Only the unit label changes (across all releases).

#example("R1 — task-symbolSearch_events.json")

The excerpts show the onset definition.

#comparison(excerpt(("… (1 rows skipped)",
"  \"onset\": {",
"    \"LongName\": \"Event onset\",",
"    \"Description\": \"Position (latency) of\n  event marker in seconds relative to the\n  start.\",",
"    \"Units\": \"seconds\"",
"  },",
"… (57 rows skipped)",), marked: (4,)), excerpt(("… (1 rows skipped)",
"  \"onset\": {",
"    \"LongName\": \"Event onset\",",
"    \"Description\": \"Position (latency) of\n  event marker in seconds relative to the\n  start.\",",
"    \"Units\": \"s\"",
"  },",
"… (58 rows skipped)",), marked: (4,)), left: [HBN-EEG .json], right: [Proposed .json])

=== A05. Correct the dataset-source key <a05>

All release `dataset_description.json` files misspell `SourceDatasets` as `SourceDatesets`. The repair corrects the key, retaining its source URL and the dataset identity/license.

#example("R9 — dataset_description.json")

#comparison(excerpt(("… (24 rows skipped)",
"    \"SourceDatesets\": [",
"        {",
"            \"URL\":\n  \"s3://fcp-indi/data/Projects/HBN\"",
"        }",
"    ],",
"… (14 rows skipped)",), marked: (1,)), excerpt(("… (42 rows skipped)",
"  \"SourceDatasets\": [",
"    {",
"      \"URL\":\n  \"s3://fcp-indi/data/Projects/HBN\"",
"    }",
"  ]",
"… (1 rows skipped)",), marked: (1,)), left: [HBN-EEG .json], right: [Proposed .json])

=== A06. Correct HED event descriptions <a06>

HED annotations describe events in a form that software can interpret. They can come from mappings in `*_events.json` or from a `HED` column in `*_events.tsv`. The three problems below affect the contrast change and sequence learning tasks. The repair changes annotations, retaining event times and behavioral values.

*1. Contrast change: feedback is attached to the wrong event.*

In this task, a target changes contrast, the participant presses a mouse button, and a green or red face subsequently indicates whether the answer was correct. This produces the button press event and the display of feedback event.

#example("R1 — task-contrastChangeDetection_events.json")

The `_events.json` in HBN-EEG describes the event in `value.HED.right_target`. The issue is that it also tries to attach feedback 2.4 seconds later. `{feedback}` reads the *target row's own* feedback cell; it does not look ahead to the participant's actual response.

#comparison(excerpt((
"((Def/right-target),",
" Duration/1600 ms),",
"(Delay/1600 ms,",
" (Def/right-comeback),",
" Duration/800 ms),",
"(Delay/2400 ms,",
" ({feedback}), Duration/400 ms)",
), marked: (5,6)), excerpt((
"((Def/right-target),",
" Duration/1600 ms),",
"(Delay/1600 ms,",
" (Def/right-comeback),",
" Duration/800 ms)",
)), left: [HBN-EEG `_events.json`], right: [Proposed `_events.json`])

#example("R1 — sub-NDARAM704GKZ_task-contrastChangeDetection_run-1_events.tsv")

Here the target's feedback cell is `n/a`; `smiley_face` is stored on the later response row. The original JSON also maps `smiley_face` directly to a visual-feedback annotation, incorrectly placing that display at the button press. The repair removes both of these feedback mappings. It associates one target, one consistent response and the following code-5 marker, then adds the feedback annotation to that marker's row.

#comparison(excerpt((
"onset  event_code feedback",
"… (2 rows skipped)",
"38.232 5          n/a",
"41.036 9          n/a",
"43.004 13         smiley_face",
"43.434 5          n/a",
"46.234 9          n/a",
"… (73 rows skipped)",
), headers: (0,), marked: (3,4,5)), excerpt((
"((Visual-presentation,",
"  (Feedback, True),",
"  (Foreground-view,",
"    (Center-of, Computer-screen),",
"    (Circle, Green)),",
"  Label/Smiley-face),",
" Duration/400 ms)",
), marked: (1,6)), left: [HBN-EEG `_events.tsv`], right: [Proposed `HED` cell at 43.434 s])

The target-to-button interval is *1.968 s*; the target-to-code-5 interval is *2.398 s*, close to the nominal 2.4 s. Code 5 is named `contrastTrial_start` in the source. Interpreting it as the start of feedback, and retaining a 400 ms feedback duration, uses the task protocol; the marker is not an independent measurement of what appeared on screen.

Missing, repeated or inconsistent responses remain unannotated and are counted in `code/recording_quality.tsv`. If target-to-code-5 timing differs from 2.4 s by more than *50 ms*, the recording's target annotations omit fixed 1.6/0.8-second phase lengths, and that trial's feedback annotation omits a duration. This affects 6,061 intervals in 550 recordings. Original times, outcome cells and nominal task descriptions remain available.

*2. Sequence learning: different dot positions refer to dot 1.*

This task shows a sequence at six or eight dot positions. In the source dictionary, `ON` means a dot turns black and `OFF` means it turns white again. Definitions for the individual positions already exist, but the HED mappings for dots 2–8 incorrectly reuse dot 1. The repair uses the matching existing definition; where none exists, the event label is retained without an invented HED meaning.

#example("R1 — task-seqLearning8target_events.json")

Selected entries from `value.HED` are shown. This correction affects 1,890 recordings / participants.

#comparison(excerpt((
"\"dot_no2_ON\":",
"  \"(Def/dot-no-1, Onset)\",",
"\"dot_no2_OFF\":",
"  \"(Def/dot-no-1, Offset)\"",
), marked: (1,3)), excerpt((
"\"dot_no2_ON\":",
"  \"(Def/dot-no-2, Onset)\",",
"\"dot_no2_OFF\":",
"  \"(Def/dot-no-2, Offset)\"",
), marked: (1,3)), left: [HBN-EEG `_events.json`], right: [Proposed `_events.json`])

*3. Sequence learning: an OFF event occurs before any matching ON event.*

A recording can begin with a dot-OFF marker: it records a return to white, but contains no preceding ON marker. A HED `Offset` would close an interval whose `Onset` is absent. The recorded event is retained as a point event, without inventing an earlier onset.

#example("R1 — sub-NDARAC904DMU_task-seqLearning8target_events.json")

At 0 s, the `.set` identifies `dot_no7_OFF`; A01 restores this label in the TSV, where it was `n/a`. A06 adds `hed_annotation = initial_offset` on that row. The left excerpt is the `value.HED` mapping inherited from `task-seqLearning8target_events.json`; the right is the new recording-specific `hed_annotation.HED` mapping. Other rows keep their normal annotations through this new column.

#comparison(excerpt((
"\"dot_no7_OFF\":",
"  \"(Def/dot-no-1, Offset)\"",
), marked: (1,)), excerpt((
"\"initial_offset\":",
"  \"Label/Initial-offset\"",
), marked: (0,1,)), left: [HBN-EEG `_events.json`], right: [Proposed `_events.json`])

The quality table records annotation changes and unresolved cases separately from EEG usability. Unsupported event categories retain their labels without invented HED meanings.

=== A07. Complete verified channel descriptions <a07>

Some `*_channels.tsv` files lack channel types and units. After checking the 129-channel EGI layout against .set metadata, the repair fills `EEG`/`uV` in *5,913 tables / 963 participants*.

#example("R11 — sub-NDARAC296UCB_task-DespicableMe_channels.tsv")

#comparison(excerpt((
"name type units",
"E1   n/a  n/a",
"E2   n/a  n/a",
"E3   n/a  n/a",
"… (125 rows skipped)",
"Cz   n/a  n/a",
), marked: (1,2,3,5,), headers: (0,)), excerpt((
"name type units",
"E1   EEG  uV",
"E2   EEG  uV",
"E3   EEG  uV",
"… (125 rows skipped)",
"Cz   EEG  uV",
), marked: (1,2,3,5,), headers: (0,)))

=== A08. Add missing EEG channel counts <a08>

Some `*_eeg.json` files lack `EEGChannelCount`. The repair derives the count from the verified `*_channels.tsv` types and the corresponding `.set` header, adding it to *1,557 files / 186 participants*. Every HBN-EEG recording then has a count.


#example("R3 — sub-NDARAA948VFH_task-DespicableMe_eeg.json")

#comparison(excerpt(("… (4 rows skipped)",
"  \"RecordingType\": \"continuous\",",
"  \"RecordingDuration\": 172.24,",
"  \"SamplingFrequency\": 500,",
"  \"SoftwareFilters\": \"n/a\"",
"}",), marked: ()), excerpt(("… (4 rows skipped)",
"  \"RecordingType\": \"continuous\",",
"  \"RecordingDuration\": 172.24,",
"  \"SamplingFrequency\": 500,",
"  \"SoftwareFilters\": \"n/a\",",
"  \"EEGChannelCount\": 129",
"}",), marked: (5,)), left: [HBN-EEG .json], right: [Proposed .json])

All participants still lack further hardware/acquisition metadata, such as `EEGGround`, `CapManufacturer`, `CapManufacturersModelName`, `SoftwareVersions` and `DeviceSerialNumber`. These gaps are logged. Specific values for these attributes could not be found in the S3 data. The #link("https://fcon_1000.projects.nitrc.org/indi/cmi_healthy_brain_network/EEG_Eyetracking_Protocol.html")[HBN protocol] does supply general system information, including EGI HydroCel equipment and a Cz reference, but this has not been used to fill these fields.

=== A09. Preserve assessments and expose recording coverage <a09>

The original per-task quality tables and participant availability columns are not a complete inventory of every evidenced source/BIDS recording. They contain 174 rows marked as available, without there being a corresponding recordings in the dataset. The opposite (marked unavailable but recording exists) is the case for two recordings.

The proposal adds `code/recording_quality.tsv` and its JSON dictionary, combining source presence, HBN-EEG ratings, task availability, issue flags and ET association. It contains 31,251 rows: 26,672 HBN-EEG recordings and 4,579 source-only or unresolved candidates.

#example("R4 — participants.tsv")

For NDARBJ482HJL, contrast change run 1, The HBN-EEG status is `available`, but `in_upstream_bids = 0`; the S3 signal export `SAIIT_2AFC_Block1.mat` exists, so `in_s3 = 1`. The new inventory makes that distinction visible.

Separately, all *140* original quality files are comma-delimited despite their `.tsv` extension and are now rewritten with tabs.

The sheet also assigns automatic recommendations, described under #link(<quality>)[Quality checks and verification].

=== A10. Task overlaps <a10>

Task files can contain other task segments, as illustrated in this contrast change recording which also contains a 170.55s long video recording. A `break cnt` or boundary marker alone (without an identified extra task/run start) is not treated as a quality problem.

#example("R1 — sub-NDARAM704GKZ_task-contrastChangeDetection_run-2_events.tsv")

#block(sticky: true)[*HBN-EEG .tsv*]

#excerpt((
"onset   duration sample value                  event_code feedback",
"… (73 rows skipped)",
"204.818 n/a      102409 right_buttonPress      13         smiley_face",
"205.6   n/a      102800 contrastTrial_start    5          n/a",
"211.976 n/a      105988 break cnt              break cnt  n/a",
"236.522 n/a      118261 9999                   9999       n/a",
"237.558 n/a      118779 video_start            83         n/a",
"408.112 n/a      204056 video_stop             103        n/a",
"408.66  n/a      204330 break cnt              break cnt  n/a",
"439.336 n/a      219668 contrastChangeB3_start 96         n/a",
"445.07  n/a      222535 contrastTrial_start    5          n/a",
"449.47  n/a      224735 right_target           9          n/a",
"… (73 rows skipped)",
), marked: (4,5,6,7,8,9,), headers: (0,))

The intended #link("https://fcon_1000.projects.nitrc.org/indi/cmi_healthy_brain_network/EEG_Eyetracking_Protocol.html")[HBN protocol] does place a movie task between contrast blocks 2 and 3 (contrast block 2 → Despicable Me → contrast block 3). However, it is unexpected that the entire movie recording is included in just the `contrastChangeDetection` file.

The `issue_a10_task_overlap` column in `code/recording_quality.tsv` distinguishes the following outcomes. A task-start marker can identify an entire embedded task or just a short spillover fragment; the flag does not establish how much of that task was recorded:

*Completed comparison, 23 November 2026:* checks cover all 3,155 participants. Extra task/run starts were identified in 1,685 recordings from 1,057 participants. The final counts below are also stored in the repaired and augmented recording-quality tables.

- `present_counterpart_available_matches`: the extra embedded task/run has a unique separate HBN-EEG file, and its shared signal interval matches exactly at the corresponding start markers (841 recordings).
- `present_counterpart_available_differs`: the separate counterparts exist, but at least one shared signal interval differs at marker alignment (487 recordings).
- `present_counterpart_available_unknown`: the separate counterparts exist, but at least one amplitude comparison is inconclusive and none establishes a difference (99 recordings).
- `present_counterpart_missing`: at least one embedded task/run has no separate HBN-EEG counterpart (258 recordings). The inventory identifies 280 missing task/run identities across 229 participants. The mixed file is retained so the embedded data remain accessible.
- `unresolved`: unclear task identity or ambiguous counterpart files prevent classification. Source-only (only in S3) entries that have not been inspected also receive this value (e.g. NDARAC349YUC symbol search, which has WISC_ProcSpeed.mat only in S3 but not in HBN-EEG). This applies to 4,579 inventory entries.
- `absent`: no identified extra task/run start was found (normal case; 24,987 recordings).

The comparison checks every sample and channel in the common interval, ending at the next task start or file end. Repeated start markers, different sampling rates or channel order, or fewer than 32 common samples leave amplitude comparison unknown. When several tasks are embedded, a missing counterpart takes priority; otherwise an established difference takes priority over unknown comparisons.

=== A11. Flag uncertain answer-to-response associations <a11>

In symbol search, the participant sees 15 problems at once. Each screen row contains two target symbols, five search symbols, and YES/NO response boxes. Participants click whether either target appears in the search set, work for up to two minutes, and may correct earlier answers. The S3 `.mat` file stores the final answers by screen-row position; the EEG `_events.tsv` stores response markers in time order. Those two orders are not necessarily the same.

#example("R1 — sub-NDARCZ947WU5_task-symbolSearch_events.tsv")

The S3 source is `NDARCZ947WU5/Behavioral/mat_format/NDARCZ947WU5_WISC_ProcSpeed.mat`. Its `par.activated_resp` array contains a pair for each screen row: `[1 0]` means YES, `[0 1]` means NO, and `[2 2]` means unanswered. The following illustration decodes all 15 positions on page 1. `Y` = YES, `N` = NO, and `–` = unanswered.

#block(sticky: true)[*S3 `.mat`, decoded final answer grid*]
#excerpt((
"Screen row:     1  2  3  4  5  6  7  8  9 10 11 12 13 14 15",
"Saved answer:   N  Y  N  N  –  Y  N  Y  N  N  N  Y  N  –  –",
), headers: (0,))

Twelve screen rows have answers: 1–4 and 6–13. The HBN-EEG file also contains twelve response markers, however its `user_answer` column only reproduces screen positions 1–12, including unanswered position 5, and omits answered position 13. Below is the complete response sequence from that TSV column.

#block(sticky: true)[*HBN-EEG `_events.tsv`, decoded `user_answer` sequence*]
#excerpt((
"EEG response:   1  2  3  4  5  6  7  8  9 10 11 12",
"Saved answer:   N  Y  N  N  –  Y  N  Y  N  N  N  Y",
), headers: (0,))

The fact that subjects can go back and correct answers creates ambiguity here. Ideally, each response would identify the page, screen row and answer selected at that moment. A final answer grid cannot establish that click history when corrections or repeated clicks are possible. The 100 affected recordings therefore retain their HBN-EEG answers and receive an uncertainty flag; the source does not justify automatically shifting their answers.

=== A12. Behavioral values and configured blocks <a12>

S3 behavioral files and EEG event sequences disagree in *12 recordings / 12 participants*: six target-direction comparisons, one response-side comparison, four duration comparisons and one configured-block count (`NDAREE675XRY` has five blocks configured in its sequence-learning source but only one represented in EEG). Values and signals are retained and `issue_a12_behavior_disagreement` records the unresolved correspondence. Source-comparison findings require matching event and behavioral-file hashes.

#example("R5 — sub-NDARJM296MDW_task-contrastChangeDetection_run-2_events.tsv")

In `NDARJM296MDW/Behavioral/mat_format/NDARJM296MDW_SAIIT_2AFC_Block2.mat`, `trialLR` identifies left/right targets by 1/2 and `CD_TG` maps those sides to EEG codes 8/9. Fourteen of 24 target directions disagree with the HBN-EEG `_events.tsv`. The first five are shown below. The sources do not establish which sequence is correct.

#comparison(excerpt((
"trialLR(1:5) = [1 1 1 2 2]",
"par.CD_TG    = [8 9]",
), marked: (0,), headers: ()), excerpt((
"onset   value        event_code",
"… (3 rows skipped)",
"92.058  right_target 9",
"… (1 rows skipped)",
"97.256  left_target  8",
"… (2 rows skipped)",
"105.656 right_target 9",
"… (3 rows skipped)",
"114.058 left_target  8",
"… (2 rows skipped)",
"122.458 right_target 9",
), marked: (2,6,8,), headers: (0,)), left: [S3 .mat, decoded], right: [HBN-EEG `_events.tsv`])


=== A13. Missing or inconsistent movie markers <a13>

Movie markers disagree with source expectations or are missing/repeated in *98 recordings / 89 participants*: 15 source-comparison findings and 90 recording-marker findings, seven overlapping. `issue_a13_movie_markers` identifies this check separately from behavioral-value disagreements.

#example("R1 — sub-NDARDL511UND_task-FunwithFractals_events.tsv")

The file starts Fractals (82), then starts and stops Diary of a Wimpy Kid (81/101); Fractals' own stop (102) is missing, meaning there is no complete Fractals start/stop pair.

#block(sticky: true)[*HBN-EEG .tsv*]

#excerpt((
"onset   duration sample   value       event_code",
"0       n/a      0        9999        9999",
"6.568   n/a      3284     video_start 82",
"87.162  n/a      43581    9999        9999",
"91.544  n/a      45772    video_start 81",
"208.944 n/a      104472   video_stop  101",
"209.503 n/a      104751.5 boundary    boundary",
), marked: (2,4,5,), headers: (0,))

=== A14. Event duration beyond the signal <a14>

An event's stated duration extends beyond the available EEG in *two recordings / two participants*, both R10 surround suppression run 1: `NDARUZ062BWR` and `NDARXU409JCU`. This differs from task overlap: neither has an A10 flag.

#example("R10 — sub-NDARUZ062BWR_task-surroundSupp_run-1_events.tsv")

The final four rows are shown. Its `.set` contains 217,037 samples at 500 Hz: 434.074 seconds of EEG. The final onset is 434.072 seconds, with a stated stimulus duration of 2.4 seconds.

#block(sticky: true)[*HBN-EEG .tsv*]

#excerpt((
"onset   duration sample value       event_code",
"… (126 rows skipped)",
"427.714 n/a      213857 fixpoint_ON 4",
"428.238 2.4      214119 stim_ON     8",
"433.554 n/a      216777 fixpoint_ON 4",
"434.072 2.4      217036 stim_ON     8",
), marked: (5,), headers: (0,))

BIDS defines #link(bids-events)[duration as the event’s duration]. The repair retains the value and records the limitation in `code/recording_quality.tsv` (`issue_a14_event_extent`).

=== A15. Six-channel exports without usable EEG <a15>

R7 `NDARBA381JGH` (six recordings) and `NDARUJ292JXV` (four) contain only six unidentified channels. Inspecting all ten HBN-EEG signals and their S3 MATLAB sources reveals the same pattern: four constant channels (0, −400, +400, 0), one sinusoidal channel and one two-level square-wave channel. These appear to be test signals; the acquisition cause has not been established.

#example("R7 — NDARBA381JGH/EEG/raw/mat_format/RestingState.mat")

#block(sticky: true)[*S3 .mat, decoded*]

#excerpt((
"nbchan     = 129",
"data.shape = (6, 220387)",
"chanlocs   = []",
"data[0, :4] = [   0,    0,    0,    0]",
"data[1, :4] = [-400, -400, -400, -400]",
"data[2, :4] = [ 400,  400,  400,  400]",
"data[5, :4] = [   0,    0,    0,    0]",
), marked: (0,1,2,))

The repair retains these files and flags `issue_a15_unidentified_channels`. All other 26,662 HBN-EEG headers have 129 channels and positive sample counts/rates.

#pagebreak()

== B. Additional behavioral information

Most behavioral information from the S3 releases is already represented in HBN-EEG. `hbn_augment` adds three selected sets of information from the S3 `Behavioral/` MATLAB exports, independently of ET availability. Existing event columns and EEG measurements remain unchanged.

#table(columns: (auto, 2.6fr, auto, auto), inset: 4pt,
  table.header([*Issue*], [*Addition*], [*Recordings*], [*Subjects*]),
  [B01], [Selected task settings and source acquisition flags], [16,788], [2,589],
  [B02], [Planned wait before each verified contrast target], [5,256], [1,942],
  [B03], [Movie presentation position and source clip basename], [3,774], [975],
)



=== B01. Retain selected task settings

A small custom metadata object `HBNTaskParameters` is added to each matched recording's `_eeg.json`. The whitelist includes source EEG/ET/calibration flags; contrast flicker frequencies and planned target count; surround flicker frequency and planned stimulus duration in seconds; sequence target/repetition counts; and symbol-search planned page count. Movie exports contribute only the flags, because some retain unrelated contrast-task parameters.
B01, B02 and B03 each have a controlled status column in the recording-quality sheet.

#example("R1 — sub-NDARAC904DMU_task-contrastChangeDetection_run-1_eeg.json")

#comparison(excerpt((
"par.FlickF      = [20, 25]",
"par.numtargets = 24",
"par.recordEEG  = 1",
"par.useEL      = 1",
"par.useEL_Calib = 1",
)), excerpt((
"\"HBNTaskParameters\": {",
"  \"FlickerFrequencyHz\": [20.0, 25.0],",
"  \"PlannedTargetCount\": 24.0,",
"  \"SourceEEGRecordingFlag\": 1.0,",
"  \"SourceEyeTrackingFlag\": 1.0,",
"  \"SourceEyeCalibrationFlag\": 1.0",
"}",
), marked: (1, 2, 3, 4, 5)), left: [S3 .mat, decoded], right: [HBN_BIDS `_eeg.json`])

These are fixed source settings set by the task. Another custom attribute `HBNBehavioralSources` stores the source paths and hashes.

=== B02. Add planned waits before contrast targets

The MATLAB `trialITI` values describe the planned wait before each contrast target. A new `planned_iti` column places the value on the target row of `_events.tsv`, with a seconds definition in `_events.json`. Other rows receive `n/a`.

#example("R1 — sub-NDARAC904DMU_task-contrastChangeDetection_run-1_events.tsv")

The same five consecutive rows are shown on both sides, selecting only relevant columns. The original first two target waits are both 2.8 seconds.

#comparison(excerpt((
"onset   event_code",
"39.484  5",
"42.284  9",
"44.414  13",
"44.684  5",
"47.484  9",
), headers: (0,)), excerpt((
"onset   event_code planned_iti",
"39.484  5          n/a",
"42.284  9          2.8",
"44.414  13         n/a",
"44.684  5          n/a",
"47.484  9          2.8",
), headers: (0,), marked: (2, 5)), right: [HBN_BIDS `_events.tsv`])

The named block must have one start marker, identical target directions and counts, and at least three target times whose source/EEG clock fit has at most 20 ms maximum residual. The check stops at the next task or block boundary, so a mixed recording does not borrow values from another block. This adds 126,168 target values; 61 recordings failed the timing check and 67 failed target/block correspondence.

=== B03. Retain verified movie order and clip names

Two text fields are added to `_eeg.json`: `HBNMoviePresentationIndex` and `HBNSourceClipFile`. Presentation position (the order in which the movies were presented) comes from the cumulative source movie history, checked against `movie_order.mat`, the clip basename, marker codes, permutation and source visit fields. The EEG must contain the corresponding single movie start/stop pair.

#example("R4 — sub-NDARAC349YUC_task-DiaryOfAWimpyKid_eeg.json")

Despite the filename `NDARAC349YUC_Video1.mat`, the saved history for this subject contains the presentation order 1. Fun with Fractals, 2. Despicable Me, 3. Diary of a Wimpy Kid. The verified presentation position is therefore 3:

#comparison(excerpt((
"\"TaskName\": \"DiaryOfAWimpyKid\"",
)), excerpt((
"\"TaskName\": \"DiaryOfAWimpyKid\",",
"\"HBNMoviePresentationIndex\": 3,",
"\"HBNSourceClipFile\":",
"  \"Diary_of_a_Wimpy_Kid_Trailer.mp4\"",
), marked: (1, 2, 3)), left: [HBN-EEG `_eeg.json`], right: [HBN_BIDS `_eeg.json`])

Among matched movie sources, 23 recordings had conflicting movie/visit/marker evidence and six lacked a unique usable order export. No index was guessed for them. 

#pagebreak()

== C. Eye-tracking integration

#text(size: 9pt)[#table(columns: (0.5fr, 4fr), inset: 4pt,
  table.header([*Issue*], [*Conversion decision*]),
  [#link(<c01>)[C01]], [Match inconsistent ET filenames to the correct EEG participant, task and run],
  [#link(<c02>)[C02]], [Represent missing and irregular samples on a regular time grid without discarding observations],
  [#link(<c03>)[C03]], [Express the EEG–ET clock offset and rate difference in the output timing],
  [#link(<c04>)[C04]], [Map source columns, units and eye identities to BIDS fields],
  [#link(<c05>)[C05]], [Mark supported all-zero measurement groups as missing],
  [#link(<c06>)[C06]], [Preserve vendor-detected events, messages and their native timestamps],
  [#link(<c07>)[C07]], [Combine source acquisition metadata with explicit assumptions and overrides],
  [#link(<c08>)[C08]], [Record conversion decisions, timing errors and missing-sample counts],
  [#link(<c09>)[C09]], [Distinguish exported eye columns from usable measurements of that eye],
)]

SMI exports each recording as two text files, each with its own metadata header. The `_Samples.txt` file contains individual eye measurements (`SMP`) interleaved with task messages (`MSG`). The `_Events.txt` file contains the manufacturer's detected fixations, saccades and blinks, and repeats task messages as `UserEvent` rows. These are source files; their conversion into BIDS is described in C01–C09. The following shows two examples for clarification:

#example("R2 — NDARAB793GL3_WISC_ProcSpeed_Samples.txt")

The excerpt selects time, row type, trial, and three left-eye measurements. `L Dia X` is pupil diameter along the X axis; `L POR X/Y` are gaze coordinates. All three measurements shown use pixels. A `MSG` row instead carries text after its first three fields, so it must not be interpreted as a measurement row.

#excerpt((
"… (5 rows skipped)",
"## Sample Rate:       120",
"… (3 rows skipped)",
"## Number of Samples: 13779",
"… (28 rows skipped)",
"Time        Type Trial L Dia X [px] L POR X [px] L POR Y [px]",
"… (1 rows skipped)",
"3503399370  SMP  1     18.10        292.92       340.77",
"3503399584  MSG  1     # Message: 92",
"3503407738  SMP  1     18.00        308.12       316.24",
"… (13,795 rows skipped)",
), headers: (5,), marked: (7,8,9,))

#example("R2 — NDARAB793GL3_WISC_ProcSpeed_Events.txt")

Different event types have different layouts. Here, the excerpt selects the first six fields, which are common to fixations and saccades. `L` denotes the left eye. The same task message `92` also appears in this file as a `UserEvent` at timestamp `3503399584` (outside this excerpt). Both files use microseconds for their native timestamps; the event durations below are also in microseconds.

#excerpt((
"… (3 rows skipped)",
"Version:     IDF Event Detector 3.0.18",
"Sample Rate: 120",
"… (4 rows skipped)",
"Event Type Trial Number Start      End        Duration",
"… (30 rows skipped)",
"Saccade L  1     1      3503399370 3503432728 33358",
"Fixation L 1     1      3503432728 3503507885 75157",
"… (905 rows skipped)",
), headers: (4,), marked: (6,7,))

=== C01. Match inconsistent ET filenames <c01>

ET recordings come from S3 and have inconsistent naming, which cannot be accounted for with fuzzy name matching. A numbered ET movie filename such as `Video1` establishes neither a fixed movie title nor its actual position in the saved presentation history. We use the ET Movie message start/stop pairs to identify movies: 81/101 = Diary of a Wimpy Kid, 82/102 = Fun with Fractals, 83/103 = Despicable Me, and 84/104 = The Present. 

#example("R2 — NDARAB793GL3_Video2_Events.txt")

`Video2` has events 83/103 and therefore matches Despicable Me.

All 3,155 HBN-EEG participant IDs have twelve alphanumeric characters; the exceptions below concern S3 names. Matching preserves directory identity without requiring one fixed ID length, accepts separators `_`, `__` and `-`, and maps documented task aliases such as `NODOOR_`. The exceptions are handled as follows:

#text(size: 9pt)[#table(columns: (1.35fr, 2fr), inset: 4pt,
  table.header([*Source irregularity*], [*Current handling*]),
  [Extra filename digit: five documented directory IDs], [Treat the appended digit as a naming error. For example, `NDARXF358XGE1_…` belongs to `NDARXF358XGE/` (R4). The directory ID is retained; original source files are not renamed.],
  [`NDARJ257ZU2_` and `NDARJH99CWH_` folders], [The historical inventory contains 24 Samples/Events pairs with extra underscore. These subjects have S3 EEG but no matching HBN-EEG participant, so their ET is outside this release's scope],
  [`NDARRV837BZQ`: `5008455_Video4`], [The pair is byte-identical to the correctly named pair. It is reported as a duplicate; the subject is retained],
  [`NDARJW326UED`: `.txt.save`], [Line 66 contains `21.32C`, whereas the normal Events file has `21.32`. Only the backup is ignored; normal recordings remain candidates],
  [Task aliases and unmatched tasks], [`vis_learn` needs a unique six/eight-target match. `WISC_2nd` and calibration remain unmapped; numbered movies need identifying messages],
)]

Differing candidates remain ambiguous. IDF and alternative TSV sources are inventoried but not read by `smi2bids`; their additional usable coverage is unknown.

=== C02. Preserve gaps in irregular ET samples <c02>

BIDS represents a continuous physiological recording using a starting time (`StartTime`) and a sampling rate (`SamplingFrequency`). Together, these define an evenly spaced time grid: at 500 Hz, successive rows are 2 ms apart. A reader can therefore calculate a row's time from its position in the file. The SMI source instead gives each observed sample its own timestamp. Samples can be missing, and the observed times need not fall exactly on an evenly spaced grid. Simply packing the remaining samples into consecutive rows would close the gaps and assign incorrect times. The conversion follows the #link(physio)[BIDS physiological-recording format] while retaining the original timestamps.


The converter begins with the sampling rate stated in the source header, then tries to fit an evenly spaced grid across the recording.

If this gives distinct, increasing positions and every sample is within one tenth of a sampling interval from its assigned gridline/tick, that grid is retained. If not, the following methods are used to get a better fit:

The grid can be shifted slightly to allow for a better fit

#block(breakable: false)[
The following schematic excerpt assumes an already fitted 2 ms period (500 Hz). Moving all ticks 0.10 ms later reduces the largest mismatch shown from 0.30 ms to 0.20 ms, meeting the 10% bound. The observed timestamps stay unchanged; the spacing between ticks also stays unchanged.

#text(size: 9pt)[#table(columns: (1fr, 1fr, 1fr, 1fr, 1fr), inset: 4pt,
  table.header([*Observed time*], [*Original tick*], [*Absolute error*], [*Shifted tick*], [*Absolute error*]),
  [0.00 ms], [0.00 ms], [0.00 ms], [0.10 ms], [0.10 ms],
  [2.30 ms], [2.00 ms], [0.30 ms], [2.10 ms], [0.20 ms],
  [4.10 ms], [4.00 ms], [0.10 ms], [4.10 ms], [0.00 ms],
)]
]

The implementation checks every sample in the recording and uses the smallest shift that satisfies the bound, when one exists.

If this is insufficient, each timestamp is assigned directly to the nearest tick, avoiding accumulated rounding errors from successive gaps. If two samples request the same position, the later sample takes the next free position. For example, requested positions `[0, 1, 1, 4]` become `[0, 1, 2, 4]`; position 3 remains empty.

An additional method is to insert `n/a` rows to compensate for missing samples:

#table(columns: (1fr, 1fr, 1fr),
  table.header([*Illustration at 500 Hz*], [*Output row*], [*Measurement*]),
  [1,000 ms], [0], [observed],
  [1,002 ms], [1], [observed],
  [1,004 ms; no observed sample], [2], [*n/a row inserted*],
  [1,006 ms], [3], [observed],
)

Importantly, no samples are interpolated in the process and it is possible to obtain the originally sampled data by simply removing all rows whose timestamp is `n/a`.

#example("R2 — NDARAB793GL3_WISC_ProcSpeed_Samples.txt")

In this export, 13,779 observed samples span 128.071982 seconds from first to last. Packing them consecutively at 120 Hz would shorten that span to 114.816667 seconds. The converter instead inserts 1,576 missing rows and fits a device-clock sampling rate of approximately 119.885668 Hz. The resulting 15,355 rows span 128.072023 seconds, only 0.041 ms longer than the original first-to-last interval. This compares the endpoints; individual sample timing errors are measured separately below.

The quality sheet records RMS error, maximum absolute error, and whether the *exported grid* passes the 5% and 10% bounds. At 60 Hz, 10% is approximately 1.67 ms. Only observed rows contribute to the errors; inserted rows do not. The flags describe the final grid rather than the existence of another potentially better fit.

Recordings with large grid discrepancy are still preserved. Readers cannot establish accurate timing for these using only `StartTime` and `SamplingFrequency`. Direct rounding alone limits displacement to half a period; preserving colliding samples can exceed that limit. For recordings that fail the bounds, analyses requiring precise timing must use the preserved native timestamps and their stored EEG-clock mapping. Invalid sample order and unreadable or inconsistent source files still stop conversion. The 5% and 10% thresholds are documented project diagnostics, not numerical requirements of BIDS.

=== C03. Align ET timing with EEG <c03>

C02 places samples on a grid within the ET recording. C03 places that grid on the EEG timeline.

The timing fit is the same linear regression used by #link("https://mne.tools/stable/generated/mne.preprocessing.realign_raw.html")[`mne.preprocessing.realign_raw`]. That function also crops/resamples recordings and does not return the fitted coefficients. Here only offset and scale are needed: the EEG and observed ET measurements are preserved.

Two quantities are needed: where the first ET sample belongs relative to EEG time zero, and whether a second measured by the ET clock corresponds to exactly one EEG second.

The aligner finds task markers recorded by both systems and matches their ordered codes. The match must be unique; unmatched markers at the beginning or end may be excluded from the fit, but interior mismatches are not discarded. A specific contrast-change export format uses response counters, which are decoded before matching. At least two matched markers are needed.

*Illustrative example.* Suppose the same two markers have the following times. ET time here means seconds since its first observed sample:

#table(columns: (1fr, 1fr, 1fr), inset: 4pt,
  table.header([*Shared marker*], [*ET elapsed time*], [*EEG time*]),
  [First], [0 s], [2 s],
  [Second], [100 s], [102.010 s],
)

The first ET sample belongs at EEG time 2 s. Between the markers, ET measures 100 s while EEG measures 100.010 s. The fitted relationship is therefore `EEG time = 2 + 1.0001 × ET elapsed time`. An ET event at 50 s belongs at EEG time 52.005 s.

With no grid-origin shift, this example produces `StartTime = 2`. A fitted 500 Hz ET grid becomes approximately `SamplingFrequency = 499.950005` Hz on the EEG clock: its 2 ms intervals correspond to 2.0002 ms in EEG time. The values in the sample rows are not interpolated or resampled; the JSON specifies when those rows belong.

In general, the fitted offset is $a$ and the clock scale is $b$, giving $t = a + b u$. If C02 fitted a device-clock period $p$ and moved the grid origin by $g$ seconds, the output is:

```text
StartTime = a + b * g
SamplingFrequency = 1 / (p * b)
EEG time of row k = StartTime + k / SamplingFrequency
```

This uses the #link(physio)[BIDS physiological-recording representation]. The clock correction is already included in `StartTime` and `SamplingFrequency`; a reader using those fields must not apply it again. The fit and its supporting markers are recorded for inspection. Conversion stops if a matched marker differs from the fitted line by more than 20 ms, or if the fitted clock scale differs from 1 by more than 1%. These are project choices, not BIDS requirements. Two markers determine a line exactly and cannot independently establish its accuracy.

=== C04. Convert sample columns and units <c04>

SMI iTools exports an IDF recording as a *Samples* file and an *Events* file, each with its own header. Samples contain `SMP` measurements and `MSG` messages. Events contain vendor-detected fixations, saccades and blinks, plus user messages and triggers. `smi2bids` converts the pair without rerunning event detection.

Left (`L`) and right (`R`) columns become separate `recording-eye1` and `recording-eye2` files; shared columns appear in both. The table introduces the complete supported sample families. Axis placeholders mean the corresponding lowercase x/y/z suffixes; explicit source units take precedence over defaults.

#text(size: 9pt)[#table(columns: (1.3fr, 1.8fr, 0.6fr), inset: 4pt,
  table.header([*SMI field / group*], [*Output column(s)*], [*Default unit*]),
  [`Time`], [`timestamp`], [`us`],
  [`POR X/Y` — gaze], [`x_coordinate`, `y_coordinate`], [`pixel`],
  [`Mapped Diameter`; `Dia`; `Dia X/Y/Z` — diameter], [`pupil_size`; `pupil_diameter`; `pupil_diameter_x/y/z`], [`mm`; `pixel`; `pixel`],
  [`Area` — pupil area], [`pupil_area`], [`pixel^2`],
  [`Raw X/Y/Z` — pupil position], [`raw_pupil_x/y/z`], [`pixel`],
  [`CR1 X/Y/Z`; `CR2 X/Y/Z` — reflections], [`corneal_reflection_1_x/y/z`; corresponding `_2_` fields], [`pixel`],
  [`EPOS X/Y/Z` — eye position], [`eye_position_x/y/z`], [`mm`],
  [`GVEC X/Y/Z` — gaze direction], [`gaze_vector_x/y/z`], [unset],
  [`H POS X/Y/Z`; `H ROT X/Y/Z`], [`head_position_x/y/z`; `head_rotation_x/y/z`], [`mm`; `deg`],
  [`Latency`; `Trial`; `Trigger`], [`latency`; `trial`; `trigger`], [`us`; unset],
  [Other fields], [Mechanical `snake_case`; original name retained as `SourceColumn`], [not guessed],
)]

`Type` is used for parsing and omitted. Columns start with timestamp and gaze (as required by BIDS), then pupil size when present; others retain source order. Blank cells and supplied missing tokens become `n/a`. `px` becomes `pixel`; `°` and `µs` become ASCII `deg` and `us` for MNE compatibility.

=== C05. Mark all-zero measurement groups as missing <c05>

For each eye separately, a sample's columns are divided into groups describing the same measurement. The rule applies only when the columns needed for a complete group are present:

#text(size: 9pt)[#table(columns: (1fr, 2.4fr), inset: 4pt,
  table.header([*Group*], [*SMI columns evaluated together, for one eye*]),
  [Gaze], [`POR X`, `POR Y`],
  [Pupil diameter], [All exported `Mapped Diameter`, `Dia` and `Dia X/Y/Z` fields together. Scalar diameter fields can form the group alone; if axial fields occur, both X and Y must be present],
  [Raw pupil position], [`Raw X`, `Raw Y`, plus `Raw Z` if exported],
  [First corneal reflection], [`CR1 X`, `CR1 Y`, plus `CR1 Z` if exported],
  [Second corneal reflection], [`CR2 X`, `CR2 Y`, plus `CR2 Z` if exported; evaluated separately from CR1],
  [Eye position], [`EPOS X`, `EPOS Y`, `EPOS Z`; all three required],
  [Gaze direction], [`GVEC X`, `GVEC Y`, `GVEC Z`; all three required],
)]

When all values of a given group are exactly zero, these columns instead become `n/a` for that sample.

For example: gaze `(0, 0)` becomes `(n/a, n/a)`, but `(0, 20)` remains. A direction `(0, 0, 0)` is missing; `(0, 0, 1)` remains. Only that group changes: the sample row, timestamp and other measurements survive. Pupil area, head coordinates, validity flags, messages and event tables receive no zero masking. Negative/off-screen gaze and nonzero outliers also remain.

The #link(smi-manual)[SMI BeGaze manual, §7.3], includes jointly zero gaze and zero pupil diameter in blink/lost-tracking detection. The additional group rules are empirical conversion choices, supported by an inspection of HBN recordings, where abrupt all-zero positions and zero vectors interrupt otherwise plausible measurements. Genuine single-axis zero crossings occurred, supporting the group rule over removing every zero-valued component.

=== C06. Retain eye events and task messages <c06>

Each eye produces `physio.tsv.gz` and, where applicable, `physioevents.tsv.gz`, with JSON defining their headerless columns. Ordinary EEG task events remain separate. Shared display/task metadata merges into the recording's `_events.json`.

First, the converter checks that Samples `MSG` and Events `UserEvent` rows contain the same timestamp/text pairs, including the number of repeated occurrences. Their order is not compared. A disagreement stops conversion for that pair.

The `physioevents` rows then come from the *Events file*: its messages, triggers, fixations, saccades and blinks. Existing duplicate events remain. Shared messages/triggers go to both eyes; eye-specific events go to their eye. Source order, events outside the sample interval and the manufacturer's event classifications are retained; event detection is not rerun.

#text(size: 9pt)[#table(columns: (1.1fr, 1.55fr, 1.5fr), inset: 4pt,
  table.header([*Event source*], [*Output*], [*Treatment*]),
  [`Start`; `Duration`], [`onset`; `duration`], [Native µs onset; duration converted to seconds and multiplied by clock scale],
  [Event type; `Description`], [`trial_type`; `message`], [fixation/saccade/blink/message/trigger; original text],
  [`End`; `Trial`; `Number`], [`end_timestamp`; `trial`; `event_number`], [Native end timestamp in µs; other values retained],
  [Location, dispersion, start/end location, average pupil X/Y], [`location_*`, `dispersion_*`, `start_location_*`, `end_location_*`, `average_pupil_size_*`], [Retained values; pixel units],
  [Peak/average acceleration, peak deceleration; other fields], [`peak_acceleration`, `average_acceleration`, `peak_deceleration`; `snake_case`], [Retained values; unknown units not guessed],
)]

=== C07. Add acquisition metadata <c07>

Defaults are SMI, gaze-on-screen and a top-left origin. The Samples header maps `Calibration Area` to screen resolution, `Stimulus Dimension` to physical size, and `Head Distance` to viewing distance; millimetres become metres. Full-screen calibration area and the distance interpretation need confirmation. The Events header is preserved separately, not used as a fallback.

Non-null YAML overrides inference; null keeps it. Screen origin, resolution, size and viewing distance are required after merging. Other unknown acquisition facts remain unset. Conflicting task metadata stops conversion.

=== C08. Document conversion and timing quality <c08>

These diagnostics document the conversion; they are not recording-quality grades. Unless noted otherwise, fields below are stored under `SMIConversion` in each eye's `_physio.json`.

#text(size: 9pt)[#table(columns: (1.65fr, 2.5fr), inset: 4pt,
  table.header([*Field or location*], [*Meaning*]),
  [Local `report` dictionary], [The converter's working collection of diagnostics, written as `SMIConversion`. The Python API returns output file paths, not this dictionary],
  [`SourceSamples` / `OutputSamples` / `InsertedSamples`], [Observed source rows, total output grid rows, and inserted all-`n/a` rows, respectively],
  [`NominalSamplingFrequency` / `DeviceSamplingFrequency`], [The source-header rate and the fitted grid rate, respectively, in device-clock Hz],
  [Top-level `SamplingFrequency`], [The exported rate is on the EEG clock: device-clock rate divided by `SMIConversion.ClockScale` (C03)],
  [`RMSGridResidualSeconds` / `MaximumGridResidualSeconds`], [Typical mismatch (root mean square) and largest absolute mismatch between observed timestamps and their assigned grid ticks, in device-clock seconds. Inserted rows do not contribute],
  [`GridPass5Percent` / `GridPass10Percent`], [Whether every observed sample lies within 5% or 10% of one period from its exported grid tick],
  [`GridOriginOffsetSeconds` / `GridMethod`], [How far the grid origin moved from the first native sample, in device-clock seconds, and which fitting method was used],
  [`GridCollisionPairs` / `GridShiftedSamples` / `GridMaximumExtraSlots`], [For the direct-rounding fallback: adjacent pairs requesting the same tick, samples moved beyond their requested tick, and the largest number of extra slots moved],
  [`ZeroGroupSamples` / `ZeroGazeSamples`], [Counts of source rows masked per group (C05); the gaze-only field repeats that group's count. Groups can overlap, so their counts must not be summed as distinct missing samples. Inserted rows are separate],
  [`FirstTimestamp` / `FirstTimestampReferenceSeconds` / `TimeMapping`], [First observed native timestamp, its EEG-relative time, and the formula mapping native timestamps to that clock; independent of a later grid-origin adjustment],
  [`SourceSampleHeader` / `Sources` / `Software`], [Original Samples metadata, input filenames and SHA-256 hashes, and converter identity. The Events header is stored separately as `SMISourceHeader` in the event sidecar],
  [Top-level `HBNSynchronization`], [Fit summary, marker counts, residuals, trimming and warnings. Individual matched markers are stored in each release's external build report, `anchors.tsv`],
  [`code/recording_quality.tsv`], [The four columns `et_grid_rms_error_ms`, `et_grid_max_error_ms`, `et_grid_pass_5pct` and `et_grid_pass_10pct` summarize the exported grid. Errors use EEG-clock milliseconds; flags are 1 (passes) or 0 (fails)],
)]

=== C09. Retain eye columns from monocular exports <c09>

Among 20,203 converted recordings from 2,481 participants, `NDARHT403JJJ` is the only participant whose Samples header declares `///Left`. Five converted recordings have that declaration yet contain both eye column sets: contrast change runs 2 and 3, surround suppression run 2, The Present and Diary of a Wimpy Kid. Every original right-eye gaze pair is zero in all five. Both column sets survive conversion; two files do not prove usable gaze data from both eyes. Partial left-eye losses also occur.

Direct S3 header checks found a sixth `///Left` export for this participant, `WISC_2nd`, which is not among the converted recordings. The participant's other five Samples exports declare `///Binoc`. Uniqueness across all S3-only or unconverted recordings has not been established.


= Quality checks and verification <quality>

A separate `code/recording_quality.tsv`, with its own JSON dictionary, covers *31,251 recordings and source candidates*. It records source availability, original assessments, issue flags, behavioral additions and ET conversion/timing metrics. Original quality tables remain available.

The #link("recording_quality.tsv.gz")[combined recording sheet] and its #link("recording_quality.json")[column dictionary] accompany this report. Simple rules assign provisional EEG recommendations; `recommendation_method` marks them as automatic and `recommendation_reasons` records controlled reason codes. Existing human review status is preserved.

#table(columns: (1fr, 2.8fr, 0.8fr), inset: 4pt,
  table.header([*Recommendation*], [*Meaning*], [*Recordings*]),
  [`available`], [No obstacle identified by the available checks], [19,824],
  [`caution`], [A caveat or incomplete assessment of an existing EEG recording], [6,838],
  [`unavailable`], [No delivered EEG file (4,579), or confirmed unusable (10)], [4,589],
)

`available` is not a signal-quality certification. Fixed metadata, ordinary validator warnings and ET availability/timing do not lower the EEG recommendation. Reason codes distinguish missing files from confirmed unusable signals; the original `upstream_status` remains separate and unchanged.

The complete eleven-release build covers *26,672 EEG recordings*, adding ET to *20,203*. Synchronization failed for 935; 5,534 lacked a matched supported export. BIDS 1.11.2 validation reported *zero errors and no new warnings*; 559,559 inherited warnings remain.

Preservation checks covered participant information, existing event fields outside the documented repairs, and original quality records. Independent checks compared converted ET samples and events against their sources. Subsequent A10 and recommendation-table updates were checked separately. These checks do not constitute a scientific review of every recording or a fresh full-dataset audit of EEG signal amplitudes.

== Sources

- #link(fair)[Shirazi et al., *HBN-EEG: The FAIR implementation of the Healthy Brain Network electroencephalography dataset*, bioRxiv v2 (2024)].
- BIDS 1.11.2: #link(physio)[physiological recordings and eye tracking], #link(bids-events)[events], and #link(bids-behavior)[behavioral experiments].
- #link(smi-manual)[SMI *BeGaze Manual*, v3.4 (2014), §7.3, printed page 320].

Installation and execution are described in the repository README. Build reports retain conversion outcomes and validation results outside the BIDS roots.
