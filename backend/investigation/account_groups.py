"""Explicit links are associations, not proof that every account has one owner."""


def account_details(profiles):
    by_url = {p.canonical_url: p for p in profiles}
    links = {p.canonical_url: [] for p in profiles}
    for p in profiles:
        for url in p.external_links:
            if url in by_url and url != p.canonical_url:
                edge = {"source_url": p.canonical_url, "target_url": url}
                links[p.canonical_url].append(edge)
                links[url].append(edge)
    return {
        p.id: {
            "analysis_status": "PUBLICLY_LINKED"
            if links[p.canonical_url]
            else "HAS_PUBLIC_CONTEXT"
            if p.bio or p.external_links
            else "POSSIBLE_MATCH_NO_CONTEXT",
            "public_links": list(p.external_links),
            "linked_accounts": links[p.canonical_url],
        }
        for p in profiles
    }
