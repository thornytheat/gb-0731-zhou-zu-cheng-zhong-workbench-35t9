from decimal import Decimal

from app.modules.m2_calibration.crossing import crossings
from app.modules.m6_reconcile.service import reconcile
from app.sources import Source


def row_for(result, key):
    return next(row for row in result["reconcile"]["rows"] if row["pass_id"] == key)


def test_ledger_partitions_source_lines_without_overlap(dirty_result):
    data = dirty_result["reconcile"]["ledger"]
    assert (data["raw"], data["effective"], data["duplicates"], data["isolated"], data["balanced"]) == (50, 22, 3, 25, True)
    accepted = [item[side]["trigger"]["source"]["line"] for item in dirty_result["axles"]["axes"] for side in ("left", "right")]
    discarded = [item["source"]["line"] for item in dirty_result["quarantine"] + dirty_result["debounce"]["duplicates"]]
    assert sorted(accepted + discarded) == [line for line in range(2, 55) if line not in (4, 12, 13)]


# TRAP-10
def test_decimal_rollup_matches_independently_summed_axles(dirty_result):
    trusted = [
        axis for axis in dirty_result["axles"]["axes"]
        if axis["id"] not in set(dirty_result["drift"]["suspended_axis_ids"])
    ]
    expected = sum(Decimal(axis["total_kg"]) for axis in trusted)
    ledger = dirty_result["reconcile"]["ledger"]
    assert Decimal(ledger["wheel_kg"]) == expected == Decimal("39590.01")
    held = [
        axis for axis in dirty_result["axles"]["axes"]
        if axis["id"] in set(dirty_result["drift"]["suspended_axis_ids"])
    ]
    assert Decimal(ledger["held_kg"]) == sum(Decimal(axis["total_kg"]) for axis in held) == Decimal("10000.00")
    assert Decimal(ledger["wheel_kg"]) + Decimal(ledger["held_kg"]) == Decimal("49590.01")


# TRAP-08
def test_latest_semantic_duplicate_and_inclusive_tolerance(dirty_result):
    row = row_for(dirty_result, "0007")
    # G01 疑漂暂停采信后，0007 只剩 A01、A04 的采信轮载，差额按新口径重算。
    assert (row["pass_id"], row["ticket"]["revision"], row["ticket"]["kg"], row["wheel_kg"]) == (
        "0007", 2, "20050.01", "10000.01",
    )
    assert row["held_kg"] == "10000.00"
    assert row["suspended_axle_ids"] == ["0007/A02", "0007/A03"]
    assert row["difference_kg"] == "10050.00"
    assert row["status"] == "review"
    assert row["codes"] == ["DRIFT_SUSPENDED", "WEIGHT_DIFFERENCE"]
    assert row["ticket_refs"] == ["dirty-tickets.csv:2", "dirty-tickets.csv:4"]
    assert row["drift_refs"] == ["dirty-triggers.csv:2", "dirty-triggers.csv:7",
                                 "dirty-triggers.csv:14", "dirty-triggers.csv:15"]
    assert row["wheel_refs"] == ["dirty-triggers.csv:3–4", "dirty-triggers.csv:5",
                                 "dirty-triggers.csv:10", "dirty-triggers.csv:11"]


def test_prior_balanced_receipt_cannot_clear_drift_suspension(dirty_result):
    # 旧的 50 kg 核平结论建立在疑漂轮载之上，采信变化后不得反证轮道正常。
    row = row_for(dirty_result, "0007")
    assert "DRIFT_SUSPENDED" in row["codes"]
    assert row["status"] == "review"


def test_latest_conflicting_revision_never_falls_back(dirty_result):
    row = row_for(dirty_result, "0019")
    assert row["codes"] == ["TICKET_CONFLICT", "WHEELS_INCOMPLETE"]
    assert row["ticket_refs"] == ["dirty-tickets.csv:6", "dirty-tickets.csv:8"]
    assert row["difference_kg"] is None


def test_no_weight_variance_does_not_clear_missing_wheel_evidence(dirty_result):
    row = row_for(dirty_result, "0023")
    assert (row["difference_kg"], row["codes"], row["status"]) == ("0.00", ["WHEELS_INCOMPLETE"], "review")
    assert row["review_refs"] == [f"dirty-triggers.csv:{line}" for line in range(33, 37)]


def test_bad_highest_revision_and_wrong_plate_cannot_supply_total(dirty_result):
    invalid = row_for(dirty_result, "0028")
    bad_plate = row_for(dirty_result, "0040")
    assert invalid["ticket_refs"] == ["dirty-tickets.csv:11", "dirty-tickets.csv:10"]
    assert [invalid["codes"][0], bad_plate["codes"][0]] == ["TICKET_INVALID", "TICKET_PLATE"]
    assert invalid["difference_kg"] is bad_plate["difference_kg"] is None


def test_late_ticket_right_boundary_is_excluded(dirty):
    header = "磅单号,车次,版次,车牌,签发时间,总重,单位"
    line = "WB-0007,0007,1,粤B·07612,2026-11-20T20:15:03.000+08:00,8000,kg"
    source = Source("tickets.csv", f"{header}\n{line}\n".encode())
    result = reconcile(source, crossings(dirty["passes"]), [], [], [], 0)
    actual = next(row for row in result["rows"] if row["pass_id"] == "0007")
    assert actual["codes"] == ["TICKET_TIME", "WHEELS_INCOMPLETE"]
    assert actual["ticket_refs"] == ("tickets.csv:2",)


def test_clean_rollup_has_no_review_and_zero_differences(clean_result):
    stage = clean_result["reconcile"]
    assert (stage["ledger"]["matched"], stage["ledger"]["review"], stage["ledger"]["wheel_kg"]) == (7, 0, "56000.00")
    assert {row["difference_kg"] for row in stage["rows"]} == {"0.00"}
