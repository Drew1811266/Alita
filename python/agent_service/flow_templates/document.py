from __future__ import annotations

DOCUMENT_INPUT_NODE_ID = "document-input"
DOCUMENT_PARSE_NODE_ID = "document-parse"
CONTENT_ORGANIZE_NODE_ID = "content-organize"
REPORT_GENERATE_NODE_ID = "report-generate"
TYPST_EXPORT_NODE_ID = "typst-export"
FILE_EXPORT_NODE_ID = "file-export"

DOCUMENT_FLOW_NODE_IDS = {
    DOCUMENT_INPUT_NODE_ID,
    DOCUMENT_PARSE_NODE_ID,
    CONTENT_ORGANIZE_NODE_ID,
    REPORT_GENERATE_NODE_ID,
    TYPST_EXPORT_NODE_ID,
    FILE_EXPORT_NODE_ID,
}

DOCUMENT_DATA_DEPENDENT_NODE_IDS = DOCUMENT_FLOW_NODE_IDS.difference(
    {DOCUMENT_INPUT_NODE_ID}
)


def document_flow_template() -> dict[str, object]:
    return {
        "kind": "document",
        "nodeIds": sorted(DOCUMENT_FLOW_NODE_IDS),
        "dataDependentNodeIds": sorted(DOCUMENT_DATA_DEPENDENT_NODE_IDS),
        "entryNodeId": DOCUMENT_INPUT_NODE_ID,
        "outputNodeId": FILE_EXPORT_NODE_ID,
    }
