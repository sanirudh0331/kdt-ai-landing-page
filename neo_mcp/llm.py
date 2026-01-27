"""Claude API integration for Neo Q&A."""

import os
from typing import Optional

import anthropic

SYSTEM_PROMPT = """You are a biotech/deeptech analyst for KdT Ventures.
Answer using ONLY the CONTEXT below - no outside knowledge.
If the information is not in the context, say "I don't have that in the knowledge base."
Always cite your sources by referencing the document type (PATENTS, GRANTS, POLICIES, FDA_CALENDAR) and specific identifiers when available.
Be concise but thorough. Format your response with clear structure when listing multiple items."""


def format_context(docs: list) -> str:
    """Format search results into context for the LLM."""
    if not docs:
        return "No relevant documents found."

    context_parts = []
    for i, doc in enumerate(docs, 1):
        source = doc.get("source", "unknown").upper()
        title = doc.get("title", "Untitled")
        snippet = doc.get("snippet", doc.get("document", ""))
        metadata = doc.get("metadata", {})

        # Build metadata string based on source type
        meta_parts = []
        if source == "PATENTS":
            if metadata.get("patent_number"):
                meta_parts.append(f"Patent: {metadata['patent_number']}")
            if metadata.get("assignee"):
                meta_parts.append(f"Assignee: {metadata['assignee']}")
            if metadata.get("grant_date"):
                meta_parts.append(f"Date: {metadata['grant_date']}")
        elif source == "GRANTS":
            if metadata.get("agency"):
                meta_parts.append(f"Agency: {metadata['agency']}")
            if metadata.get("total_cost"):
                meta_parts.append(f"Funding: ${metadata['total_cost']}")
        elif source == "POLICIES":
            if metadata.get("status"):
                meta_parts.append(f"Status: {metadata['status']}")
            if metadata.get("relevance_score"):
                meta_parts.append(f"Relevance: {metadata['relevance_score']}")
        elif source == "FDA_CALENDAR":
            if metadata.get("company"):
                meta_parts.append(f"Company: {metadata['company']}")
            if metadata.get("drug"):
                meta_parts.append(f"Drug: {metadata['drug']}")
            if metadata.get("date"):
                meta_parts.append(f"Date: {metadata['date']}")

        meta_str = " | ".join(meta_parts) if meta_parts else ""

        context_parts.append(
            f"[{i}] [{source}] {title}\n"
            f"{meta_str}\n"
            f"{snippet[:1000]}"
        )

    return "\n\n---\n\n".join(context_parts)


def ask_with_context(
    question: str,
    context_docs: list,
    model: str = "claude-3-5-haiku-20241022",
    max_tokens: int = 1024,
    messages: list = None,
) -> dict:
    """
    Answer a question using the provided context documents.

    Args:
        question: The user's question
        context_docs: List of search result documents
        model: Claude model to use (default: haiku for speed/cost)
        max_tokens: Maximum response length
        messages: Conversation history as list of {role, content} dicts

    Returns:
        dict with 'answer', 'sources', 'context_count', 'model'
    """
    if messages is None:
        messages = []
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {
            "answer": "AI Q&A is not configured. Please set ANTHROPIC_API_KEY.",
            "sources": [],
            "context_count": 0,
            "model": None,
            "error": "missing_api_key"
        }

    # For follow-up questions with conversation history, we can proceed without new context
    # Only return early if no context AND no conversation history
    if not context_docs and not messages:
        return {
            "answer": "I don't have any relevant documents in the knowledge base to answer this question. Try rephrasing or searching for related terms.",
            "sources": [],
            "context_count": 0,
            "model": model,
        }

    # Build the current message
    if context_docs:
        # Format context for new questions
        context_str = format_context(context_docs)
        current_message = f"""CONTEXT:
{context_str}

QUESTION: {question}

Answer based ONLY on the context above. Cite sources by their document number [1], [2], etc."""
    else:
        # Follow-up question without new context - use conversation history
        current_message = question

    try:
        client = anthropic.Anthropic(api_key=api_key)

        # Build messages array with conversation history
        api_messages = []
        for msg in messages:
            api_messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", "")
            })
        # Add current question
        api_messages.append({"role": "user", "content": current_message})

        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=SYSTEM_PROMPT,
            messages=api_messages
        )

        answer = response.content[0].text

        # Extract sources from context docs
        sources = []
        for doc in context_docs:
            source_info = {
                "source": doc.get("source", "unknown"),
                "title": doc.get("title", "Untitled"),
                "url": doc.get("url", ""),
            }
            # Add key identifiers
            metadata = doc.get("metadata", {})
            if doc.get("source") == "patents" and metadata.get("patent_number"):
                source_info["id"] = metadata["patent_number"]
            elif doc.get("source") == "grants" and metadata.get("grant_id"):
                source_info["id"] = metadata["grant_id"]
            elif doc.get("source") == "policies" and metadata.get("policy_id"):
                source_info["id"] = metadata["policy_id"]

            sources.append(source_info)

        return {
            "answer": answer,
            "sources": sources,
            "context_count": len(context_docs),
            "model": model,
        }

    except anthropic.APIError as e:
        return {
            "answer": f"AI service error: {str(e)}",
            "sources": [],
            "context_count": len(context_docs),
            "model": model,
            "error": "api_error"
        }
    except Exception as e:
        return {
            "answer": f"An unexpected error occurred: {str(e)}",
            "sources": [],
            "context_count": len(context_docs),
            "model": model,
            "error": "unexpected_error"
        }


if __name__ == "__main__":
    # Quick test
    test_docs = [
        {
            "source": "patents",
            "title": "CRISPR-Cas9 Gene Editing System",
            "snippet": "A method for editing genes using CRISPR-Cas9 technology...",
            "metadata": {"patent_number": "US12345678", "assignee": "Broad Institute"}
        }
    ]

    result = ask_with_context("What CRISPR patents exist?", test_docs)
    print(result)
