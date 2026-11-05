# Google sandbox layout review

## Prepare the Vietnamese layout case

Before bootstrapping the sandbox, set `report.locale` to `vi-VN`, use a title such as `Khảo sát trải nghiệm học tập của sinh viên`, and supply Vietnamese report text. Replace the unused `Year 4` category in the sandbox TOML with `Sinh viên năm cuối đang thực hiện đồ án tốt nghiệp`. Use that exact value for the added row in [the acceptance scenarios](google-setup-and-recovery.md#live-acceptance). Keep the same configuration for all four scenarios.

## Review every slide

After each sandbox scenario, run `uv run --locked visuaslide review-layout --config <local sandbox TOML>`. Open every PNG listed by the current command. The command writes to the project's ignored `visual_review/` directory and can overwrite thumbnails from a previous run.

| Slides | Pass criteria |
| --- | --- |
| All | Widescreen, correct order, readable Vietnamese diacritics, and no missing managed elements, unresolved placeholders, clipping, or overlapping objects. |
| Cover and context | The title and research question are legible. The method, collection period, and valid response count fit their allotted areas and match the scenario. |
| Analysis | Titles, captions, headers, and every table row are visible. Values match the saved analysis. Long labels fit without obscuring adjacent content. Chart labels and legend remain readable, and category order and series colors stay consistent across scenarios. The linked chart shows the current values. |
| Conclusion | The conclusion slide is last, and its full text is visible. |

Record pass or fail by scenario and slide, with a brief description of any defect. A successful API call alone does not establish visual acceptance.

If any managed element is missing or content overflows, correct the template or configuration and run the acceptance checks again. Keep thumbnails containing survey content out of Git.
