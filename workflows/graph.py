"""LangGraph workflow assembly for the knowledge pipeline.

Flow:
  collect → analyze → organize → review ──(passed)──→ save → END
                                    └──(not passed)──→ organize (retry)
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from workflows.nodes import (
    analyze_node,
    collect_node,
    organize_node,
    review_node,
    save_node,
)
from workflows.state import KBState, new_state


# ======================================================================
# Conditional router
# ======================================================================


def _review_router(state: KBState) -> str:
    """Decide next node after review.

    Returns:
        "save" if passed or error occurred (stop), else "organize" for retry.
    """
    if state.get("error"):
        return "save"
    return "save" if state.get("review_passed") else "organize"


# ======================================================================
# Graph builder
# ======================================================================


def build_graph() -> StateGraph:
    """Build and compile the knowledge pipeline graph.

    Returns:
        A compiled LangGraph app ready for invoke/stream.
    """
    graph = StateGraph(KBState)

    # --- Nodes ---
    graph.add_node("collect", collect_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("organize", organize_node)
    graph.add_node("review", review_node)
    graph.add_node("save", save_node)

    # --- Edges ---
    graph.set_entry_point("collect")
    graph.add_edge("collect", "analyze")
    graph.add_edge("analyze", "organize")
    graph.add_edge("organize", "review")

    # Conditional branch after review
    graph.add_conditional_edges(
        "review",
        _review_router,
        {
            "save": "save",
            "organize": "organize",
        },
    )

    graph.add_edge("save", END)

    return graph.compile()


# ======================================================================
# Main: streaming execution
# ======================================================================

if __name__ == "__main__":
    app = build_graph()
    initial_state = new_state(queries=["AI agent framework stars:>10"])

    print("=" * 60)
    print("LangGraph Knowledge Pipeline (streaming)")
    print("=" * 60)

    final = None
    for event in app.stream(initial_state):
        node_name = list(event.keys())[0]
        data = event[node_name]

        if node_name == "collect":
            sources = data.get("sources", [])
            err = data.get("error")
            if err:
                print(f"\n[{node_name}] ERROR: {err}")
            else:
                print(f"\n[{node_name}] Fetched {len(sources)} items")

        elif node_name == "analyze":
            analyses = data.get("analyses", [])
            print(f"\n[{node_name}] Generated {len(analyses)} analyses")
            for a in analyses[:3]:
                print(f"  - {a['title']}: score={a['score']}, tags={a['tags']}")

        elif node_name == "organize":
            articles = data.get("articles", [])
            print(f"\n[{node_name}] After filter/dedup: {len(articles)} articles")

        elif node_name == "review":
            passed = data.get("review_passed")
            feedback = data.get("review_feedback", "")
            print(f"\n[{node_name}] passed={passed}")
            if feedback:
                print(f"  feedback: {feedback}")

        elif node_name == "save":
            saved = data.get("saved_count", 0)
            print(f"\n[{node_name}] Saved {saved} articles")

        final = event

    # Final state summary
    if final is not None:
        merged = list(final.values())[-1]
        cost = merged.get("cost_tracker", {})
    else:
        cost = {}

    print("\n" + "=" * 60)
    print("Pipeline complete.")
    if cost:
        print(f"Total tokens → prompt: {cost.get('prompt_tokens', 0)}, "
              f"completion: {cost.get('completion_tokens', 0)}, "
              f"total: {cost.get('total_tokens', 0)}")
