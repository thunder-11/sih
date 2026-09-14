"""Qualified, agency-scoped cross-victim correlation."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.models import (
    AddressRecord, CaseComplaint, ComplaintRecord, ComplaintWallet, Entity, EntityAddressAssertion,
)
from models import Case


PUBLIC_TYPES = {"vasp", "exchange", "mixer", "bridge", "swap", "dex", "protocol", "issuer", "foundation", "treasury"}


def related_cases(case: Case, db: Session) -> dict:
    source_complaints = set(db.execute(select(CaseComplaint.complaint_id).where(CaseComplaint.case_id == case.id)).scalars())
    source_addresses = set(db.execute(select(ComplaintWallet.address_id).where(
        ComplaintWallet.complaint_id.in_(source_complaints)
    )).scalars()) if source_complaints else set()
    public_addresses = set(db.execute(select(EntityAddressAssertion.address_id).join(
        Entity, Entity.id == EntityAddressAssertion.entity_id
    ).where(Entity.entity_type.in_(PUBLIC_TYPES), EntityAddressAssertion.review_status == "reviewed",
            EntityAddressAssertion.valid_to.is_(None))).scalars())
    relevant = source_addresses - public_addresses
    shared_rows = list(db.execute(select(ComplaintWallet).where(
        ComplaintWallet.address_id.in_(relevant), ~ComplaintWallet.complaint_id.in_(source_complaints)
    )).scalars()) if relevant else []
    complaint_ids = {row.complaint_id for row in shared_rows}
    complaints = {row.id: row for row in db.execute(select(ComplaintRecord).where(
        ComplaintRecord.id.in_(complaint_ids), ComplaintRecord.agency_id == case.agency_id
    )).scalars()} if complaint_ids else {}
    case_links = list(db.execute(select(CaseComplaint).where(CaseComplaint.complaint_id.in_(complaints))).scalars()) if complaints else []
    address_rows = {row.id: row for row in db.execute(select(AddressRecord).where(AddressRecord.id.in_(relevant))).scalars()} if relevant else {}
    linked = {}
    for link in case_links:
        if link.case_id == case.id:
            continue
        matching = [row for row in shared_rows if row.complaint_id == link.complaint_id]
        linked.setdefault(link.case_id, {"case_id": link.case_id, "complaint_ids": set(), "victim_ids": set(), "shared_wallets": set()})
        linked[link.case_id]["complaint_ids"].add(link.complaint_id)
        if complaints[link.complaint_id].victim_id:
            linked[link.case_id]["victim_ids"].add(complaints[link.complaint_id].victim_id)
        linked[link.case_id]["shared_wallets"].update(
            f"{address_rows[row.address_id].chain}:{address_rows[row.address_id].canonical_address}"
            for row in matching if row.address_id in address_rows
        )
    source_victims = set(db.execute(select(ComplaintRecord.victim_id).where(
        ComplaintRecord.id.in_(source_complaints), ComplaintRecord.victim_id.is_not(None)
    )).scalars()) if source_complaints else set()
    all_victims = source_victims | {victim for item in linked.values() for victim in item["victim_ids"]}
    all_complaints = source_complaints | {complaint for item in linked.values() for complaint in item["complaint_ids"]}
    items = [{**item, "complaint_ids": sorted(item["complaint_ids"]), "victim_ids": sorted(item["victim_ids"]),
              "shared_wallets": sorted(item["shared_wallets"])} for item in linked.values()]
    qualified = len(all_victims) >= 3 and len(all_complaints) >= 3 and bool(relevant)
    return {"case_id": case.id, "linked_cases": sorted(items, key=lambda item: item["case_id"]),
            "distinct_victim_count": len(all_victims), "distinct_complaint_count": len(all_complaints),
            "possible_syndicate": qualified,
            "finding": "high-confidence shared-wallet correlation; suspected fraud, analyst review required" if qualified else None,
            "excluded_public_service_address_count": len(source_addresses & public_addresses),
            "limitations": ["Shared infrastructure alone is excluded and correlation does not prove common ownership or criminality."]}
