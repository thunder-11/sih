"""
Cross-Complaint Correlation & Syndicate Detection Engine (PRD §3 FR-6).
Finds cases sharing intermediary wallets with the current case.
"""
from sqlalchemy.orm import Session
from models import Case, CaseWallet
from config import SYNDICATE_THRESHOLD


def find_linked_cases(case_id: str, db: Session) -> dict:
    """
    Find all other cases that share at least one wallet node
    with the given case's traced graph.
    """
    source_case = db.query(Case).filter(Case.id == case_id).first()
    if source_case is None:
        return {"linked_cases": [], "possible_syndicate": False, "linked_count": 0}

    # Get all wallet addresses in this case's graph
    this_case_wallets = db.query(CaseWallet).filter(
        CaseWallet.case_id == case_id
    ).all()

    this_addresses = {(cw.wallet_address, cw.wallet_chain) for cw in this_case_wallets}

    if not this_addresses:
        return {"linked_cases": [], "possible_syndicate": False, "linked_count": 0}

    # Find other cases sharing any of these addresses
    linked = {}
    for addr, chain in this_addresses:
        other_links = db.query(CaseWallet).filter(
            CaseWallet.wallet_address == addr,
            CaseWallet.wallet_chain == chain,
            CaseWallet.case_id != case_id,
        ).all()

        for link in other_links:
            if link.case_id not in linked:
                linked[link.case_id] = {
                    "case_id": link.case_id,
                    "shared_wallets": [],
                }
            linked[link.case_id]["shared_wallets"].append(addr)

    # Enrich with case details
    linked_cases = []
    for cid, data in linked.items():
        case = db.query(Case).filter(Case.id == cid, Case.agency_id == source_case.agency_id).first()
        if case:
            linked_cases.append({
                "case_id": case.id,
                "external_complaint_id": case.external_complaint_id,
                "fraud_typology": case.fraud_typology,
                "reported_loss_amount": float(case.reported_loss_amount),
                "loss_currency": case.loss_currency,
                "status": case.status,
                "shared_wallets": list(set(data["shared_wallets"])),
                "shared_wallet_count": len(set(data["shared_wallets"])),
            })

    possible_syndicate = len(linked_cases) >= (SYNDICATE_THRESHOLD - 1)  # -1 because threshold includes current case

    return {
        "linked_cases": linked_cases,
        "possible_syndicate": possible_syndicate,
        "linked_count": len(linked_cases),
        "syndicate_threshold": SYNDICATE_THRESHOLD,
    }
