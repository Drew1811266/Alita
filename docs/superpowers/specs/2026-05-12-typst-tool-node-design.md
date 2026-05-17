# Typst Tool Node Design

## Goal

Add Typst as a first-class Alita tool node for turning generated report content into a `.typ` source artifact and a compiled PDF artifact.

## Scope

This first integration uses the Typst CLI instead of embedding the Typst Rust crates into the Tauri binary. The CLI path is resolved from `ALITA_TYPST_BIN`, then `typst` on `PATH`. Alita will not download Typst automatically in this phase.

## Workflow

The default document workflow gains a fixed tool node after the content organization and report generation nodes:

```text
document-input -> document-parse -> content-organize ┐
                              report-generate        ├-> typst-export -> file-export
```

`typst-export` receives the organized outline and generated report text, writes a Typst source file under the project artifact directory, invokes `typst compile`, and returns both the `.typ` and `.pdf` paths. `file-export` keeps the final exported file behavior by passing through the Typst output artifacts when that node is present, so users can still click the export node and preview the final file.

## Security

The tool only writes inside the project artifact directory, runs with a bounded timeout, and avoids network-dependent Typst package behavior in the default generated template. Input text is escaped into a simple Typst document, not interpolated as raw Typst code.

## Error Handling

If Typst is missing, exits with a non-zero code, times out, or does not create the PDF, the sidecar returns a structured harness error through the existing graph execution path.

## Testing

Tests cover manifest loading, executor routing, CLI invocation with a fake Typst binary, generated graph shape, default flow execution, and frontend capability labels.
