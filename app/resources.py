"""Sample resource directory for Voz Navega (demo mode).

Ported pattern from Podrá Navega's app/barriers.py: a small, clearly
labeled SAMPLE directory. Every entry is born ``verified: False`` — an
offer is never a booking, a referral, or a promise. Only a human
navigator action (outside this module) can mark an entry verified, and
the approval gate stays blocked server-side while any offered resource
is unverified.

All entries are demo data for fictional patients.
"""

from __future__ import annotations

# Barrier -> directory entry. Only transport and cost have directory
# matches (architecture §1.2 RESOURCES); the support group is always
# offered on top.
_RESOURCE_DIRECTORY = {
    "transport": {
        "name": "VTA Paratransit — medical appointment rides "
                "(sample directory) / transporte para citas médicas "
                "(directorio de muestra)",
        "type": "transport",
        "barrier": "transport",
        "offer_en": "a ride service for medical appointments",
        "offer_es": "un servicio de transporte para citas médicas",
        "source_url": "https://www.vta.org/services/paratransit",
    },
    "cost": {
        "name": "CancerCare — financial help (sample directory) / "
                "ayuda financiera (directorio de muestra)",
        "type": "financial",
        "barrier": "cost",
        "offer_en": "an organization that helps with the costs of "
                    "cancer care",
        "offer_es": "una organización que ayuda con los costos "
                    "del cáncer",
        "source_url": "https://www.cancercare.org/financial",
    },
}

_SUPPORT_RESOURCE = {
    "name": "Latinas Contra Cancer — support group (sample directory) / "
            "grupo de apoyo (directorio de muestra)",
    "type": "support_group",
    "barrier": None,
    "offer_en": "our support group, where other women share how they "
                "handled this",
    "offer_es": "nuestro grupo de apoyo, donde otras mujeres comparten "
                "cómo lo vivieron",
    "source_url": "https://www.latinascontracancer.org/",
}

_RESOURCE_LAST_CHECKED = "2026-10-13"


def _entry(template: dict) -> dict:
    entry = dict(template)
    entry["directory"] = "sample (demo)"
    entry["last_checked"] = _RESOURCE_LAST_CHECKED
    entry["verified"] = False
    return entry


def resources_for(barriers: list[dict]) -> list[dict]:
    """Attach sample-directory resources for the confirmed barriers,
    plus the support-group resource (always offered, architecture
    §1.2). ``barriers`` is a list of {"barrier": <name>, ...} dicts.
    Every returned entry starts unverified."""
    resources: list[dict] = []
    names = {b["barrier"] for b in barriers}
    for barrier in ("transport", "cost"):
        if barrier in names and barrier in _RESOURCE_DIRECTORY:
            resources.append(_entry(_RESOURCE_DIRECTORY[barrier]))
    resources.append(_entry(_SUPPORT_RESOURCE))
    return resources
