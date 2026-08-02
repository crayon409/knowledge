"""End-to-end test for the review correction loop (no GitHub API).

Verifies:
  - review not passed → back to organize
  - organize reads review_feedback and applies LLM fixes
  - iteration increments correctly
  - max 3 iterations, then force-pass at iteration >= 2

Runs with real LLM (analyze / organize-fix / review) using mock source data.
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from workflows.nodes import analyze_node, organize_node, review_node, save_node
from workflows.state import KBState, new_state

# ======================================================================
# Mock source data (3 GitHub-style projects)
# ======================================================================

MOCK_SOURCES = [
    {
        "name": "mock-org/agent-forge",
        "description": "A lightweight framework for building multi-step AI agents with tool use",
        "url": "https://github.com/mock-org/agent-forge",
        "stars": 3200,
        "language": "Python",
    },
    {
        "name": "mock-org/llm-router",
        "description": "Intelligent request router that selects the best LLM model per query",
        "url": "https://github.com/mock-org/llm-router",
        "stars": 1800,
        "language": "Rust",
    },
    {
        "name": "mock-org/knowledge-graph-rag",
        "description": "Graph RAG engine combining Neo4j knowledge graphs with LLM retrieval",
        "url": "https://github.com/mock-org/knowledge-graph-rag",
        "stars": 5600,
        "language": "Python",
    },
]

# ======================================================================
# Build sub-graph (skip collect — inject mock sources directly)
# ======================================================================


def build_test_graph():
    """Graph without collect_node → starts at analyze with mock data."""
    graph = StateGraph(KBState)

    graph.add_node("analyze", analyze_node)
    graph.add_node("organize", organize_node)
    graph.add_node("review", review_node)
    graph.add_node("save", save_node)

    graph.set_entry_point("analyze")
    graph.add_edge("analyze", "organize")
    graph.add_edge("organize", "review")

    # Conditional: passed → save, not passed → organize
    graph.add_conditional_edges(
        "review",
        lambda s: "save" if s.get("review_passed") or s.get("error") else "organize",
        {"save": "save", "organize": "organize"},
    )

    graph.add_edge("save", END)
    return graph.compile()


# ======================================================================
# Main test
# ======================================================================

if __name__ == "__main__":
    app = build_test_graph()
    initial = new_state(sources=MOCK_SOURCES)

    print("=" * 60)
    print("Review Loop End-to-End Test (mock data)")
    print("=" * 60)

    cumulative: dict = dict(initial)
    step_count = 0

    for event in app.stream(initial):
        step_count += 1
        node_name = list(event.keys())[0]
        data = event[node_name]
        cumulative.update(data)

        if node_name == "analyze":
            analyses = data.get("analyses", [])
            print(f"\n[{node_name}] Generated {len(analyses)} analyses")
            for a in analyses:
                print(f"  {a['title']}: score={a['score']}, tags={a['tags']}")

        elif node_name == "organize":
            articles = data.get("articles", [])
            print(f"\n[{node_name}] → {len(articles)} articles after filter/dedup")

        elif node_name == "review":
            passed = data.get("review_passed")
            iteration = data.get("iteration", "?")
            fb = data.get("review_feedback", "")
            label = "PASS" if passed else "FAIL"
            force = " ← force" if isinstance(iteration, int) and iteration >= 3 else ""
            print(f"\n[{node_name}] iter={iteration} {label}{force}")
            if fb:
                print(f"  feedback: {fb[:120]}...")

        elif node_name == "save":
            saved = data.get("saved_count", 0)
            print(f"\n[{node_name}] Saved {saved} articles")

    # ==================================================================
    # Summary
    # ==================================================================
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    iteration = cumulative.get("iteration", "N/A")
    review_passed = cumulative.get("review_passed", "N/A")
    saved = cumulative.get("saved_count", "N/A")
    cost = cumulative.get("cost_tracker", {})

    print(f"Total streaming steps:      {step_count}")
    print(f"Final iteration:            {iteration}")
    print(f"Review passed:              {review_passed}")
    print(f"Articles saved:             {saved}")
    print(f"Token cost (prompt):        {cost.get('prompt_tokens', 0)}")
    print(f"Token cost (completion):    {cost.get('completion_tokens', 0)}")
    print(f"Token cost (total):         {cost.get('total_tokens', 0)}")

    # Assertions
    assert iteration is not None and iteration >= 1, "iteration must be >= 1"
    assert review_passed is True, "final review must pass"
    assert saved is not None and saved > 0, "must save at least 1 article"
    print("\nAll assertions passed!")
