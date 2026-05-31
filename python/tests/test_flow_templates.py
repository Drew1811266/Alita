from agent_service.flow_templates.document import (
    DOCUMENT_DATA_DEPENDENT_NODE_IDS,
    DOCUMENT_FLOW_NODE_IDS,
    document_flow_template,
)
from agent_service.flow_templates.research import (
    RESEARCH_DATA_DEPENDENT_NODE_IDS,
    research_flow_template,
)


def test_document_template_exposes_runtime_node_id_sets() -> None:
    assert DOCUMENT_FLOW_NODE_IDS == {
        "document-input",
        "document-parse",
        "content-organize",
        "report-generate",
        "typst-export",
        "file-export",
    }
    assert DOCUMENT_DATA_DEPENDENT_NODE_IDS == {
        "document-parse",
        "content-organize",
        "report-generate",
        "typst-export",
        "file-export",
    }


def test_research_template_exposes_data_dependent_node_ids() -> None:
    assert RESEARCH_DATA_DEPENDENT_NODE_IDS == {
        "research-privacy-guard",
        "research-query-plan",
        "research-parallel-search",
        "research-source-review",
        "research-source-reading",
        "research-report-synthesis",
        "research-report-quality-check",
        "research-markdown-output",
    }


def test_flow_templates_compile_to_generic_runtime_metadata() -> None:
    document = document_flow_template()
    research = research_flow_template()

    assert document["kind"] == "document"
    assert document["nodeIds"] == sorted(DOCUMENT_FLOW_NODE_IDS)
    assert document["dataDependentNodeIds"] == sorted(DOCUMENT_DATA_DEPENDENT_NODE_IDS)
    assert research["kind"] == "research"
    assert research["dataDependentNodeIds"] == sorted(RESEARCH_DATA_DEPENDENT_NODE_IDS)
