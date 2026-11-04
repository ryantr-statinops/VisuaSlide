# Google sandbox layout review

After a successful sandbox refresh, run `visuaslide review-layout --config <local sandbox TOML>`.
The command saves PNG thumbnails under the project's ignored `visual_review/` runtime directory and prints only local paths. Open every image and check Vietnamese text, chart category order, tables, text overlap, and the final slide. A successful API call alone does not establish visual acceptance.

If any managed element is missing or content overflows, correct the template or configuration and run the acceptance checks again. Keep thumbnails containing survey content out of Git.
