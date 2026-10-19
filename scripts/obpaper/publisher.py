from typing import Any

PUBLISHER_BY_DOI_PREFIX = {
    "10.1103/": "aps",
    "10.1016/": "elsevier",
    "10.1021/": "acs",
    "10.1002/": "wiley",
    "10.1038/": "nature",
    "10.1364/": "osa",
}


def publisher_for(paper: dict[str, Any]) -> str:
    configured = str(paper.get("publisher") or "").strip().lower()
    if configured:
        return configured
    doi = str(paper["doi"]).lower()
    for prefix, publisher in PUBLISHER_BY_DOI_PREFIX.items():
        if doi.startswith(prefix):
            return publisher
    return "unknown"
