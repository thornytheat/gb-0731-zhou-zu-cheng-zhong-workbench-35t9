from decimal import Decimal
from types import SimpleNamespace

from app.modules.m5_balance.service import balance
from app.modules.m8_drift.detection import detect
from app.modules.m8_drift.service import review


def _axis(axis_id, left_kg, right_kg, group=None):
    kg = lambda value: Decimal(str(value))  # noqa: E731
    pass_id = axis_id.split("/")[0]
    return {
        "id": axis_id,
        "pass_id": pass_id,
        "group": group or f"{pass_id}/G01",
        "total_kg": kg(left_kg) + kg(right_kg),
        "left": SimpleNamespace(kg=kg(left_kg), trigger=SimpleNamespace(source=SimpleNamespace(ref=f"{axis_id}-L"))),
        "right": SimpleNamespace(kg=kg(right_kg), trigger=SimpleNamespace(source=SimpleNamespace(ref=f"{axis_id}-R"))),
    }


def _rows(axes):
    return balance(axes)["rows"]


def test_two_consecutive_same_side_heavy_axes_open_drift_suspension():
    axes = [_axis("0007/A02", 2750, 2250), _axis("0007/A03", 3000, 2000)]
    report = review(_rows(axes), axes)
    assert report["suspended_axis_ids"] == ["0007/A02", "0007/A03"]
    suspect = report["suspects"][0]
    assert (suspect["pass_id"], suspect["side"], suspect["groups"]) == ("0007", "L", ["0007/G01"])
    assert (suspect["levels"], [str(value) for value in suspect["percents"]]) == (
        ["warn", "severe"], ["10.00", "20.00"],
    )
    assert tuple(suspect["drift_refs"]) == ("0007/A02-L", "0007/A03-L")
    assert tuple(suspect["opposite_refs"]) == ("0007/A02-R", "0007/A03-R")


def test_single_heavy_axis_is_kept_as_load_evidence_without_drift():
    axes = [_axis("0007/A01", 3000, 2000)]
    report = review(_rows(axes), axes)
    assert report["suspects"] == []
    assert report["suspended_axis_ids"] == []
    assert report["streams"][0]["trusted_groups"] == ["0007/G01"]


def test_alternating_heavy_side_breaks_the_run():
    axes = [_axis("0007/A01", 3000, 2000), _axis("0007/A02", 2000, 3000)]
    report = review(_rows(axes), axes)
    assert report["counts"] == {"suspect_lanes": 0, "suspended_axes": 0, "suspended_groups": 0}


def test_normal_axis_between_two_heavy_axes_breaks_the_run():
    axes = [
        _axis("0007/A01", 3000, 2000),
        _axis("0007/A02", 2000, 2000),
        _axis("0007/A03", 3000, 2000),
    ]
    report = review(_rows(axes), axes)
    assert report["suspects"] == []


def test_right_lane_drift_is_detected_with_symmetric_rule():
    axes = [_axis("0012/A01", 2000, 3000), _axis("0012/A02", 2250, 2750)]
    report = review(_rows(axes), axes)
    assert report["suspects"][0]["side"] == "R"
    assert report["suspended_axis_ids"] == ["0012/A01", "0012/A02"]


def test_only_covered_groups_are_suspended_other_groups_remain_trusted():
    axes = [
        _axis("0007/A01", 2750, 2250, "0007/G01"),
        _axis("0007/A02", 3000, 2000, "0007/G01"),
        _axis("0007/A03", 2000, 2000, "0007/G02"),
    ]
    report = review(_rows(axes), axes)
    stream = next(item for item in report["streams"] if item["pass_id"] == "0007")
    assert stream == {"pass_id": "0007", "trusted_groups": ["0007/G02"], "suspended_groups": ["0007/G01"]}


def test_drift_scope_is_limited_to_the_pass_other_passes_stay_trusted():
    axes = [
        _axis("0007/A01", 3000, 2000, "0007/G01"),
        _axis("0007/A02", 3000, 2000, "0007/G01"),
        _axis("0012/A01", 3000, 2000, "0012/G01"),
    ]
    report = review(_rows(axes), axes)
    assert report["suspended_axis_ids"] == ["0007/A01", "0007/A02"]
    other = next(item for item in report["streams"] if item["pass_id"] == "0012")
    assert other["trusted_groups"] == ["0012/G01"]


def test_min_run_threshold_is_configurable():
    axes = [_axis("0007/A01", 3000, 2000), _axis("0007/A02", 3000, 2000)]
    assert detect(_rows(axes), axes, min_run=3)["suspended_axis_ids"] == []
    assert detect(_rows(axes), axes, min_run=2)["suspended_axis_ids"] == ["0007/A01", "0007/A02"]


def test_dirty_sample_flags_only_0007_left_lane(dirty_result):
    report = dirty_result["drift"]
    assert report["min_run"] == 2
    assert report["counts"] == {"suspect_lanes": 1, "suspended_axes": 2, "suspended_groups": 1}
    suspect = report["suspects"][0]
    assert (suspect["pass_id"], suspect["side"], suspect["axis_ids"], suspect["groups"]) == (
        "0007", "L", ["0007/A02", "0007/A03"], ["0007/G01"],
    )
    stream = next(item for item in report["streams"] if item["pass_id"] == "0007")
    assert stream["trusted_groups"] == ["0007/G02"]


def test_clean_sample_has_no_drift_suspension(clean_result):
    report = clean_result["drift"]
    assert report["suspects"] == []
    assert report["suspended_axis_ids"] == []
    assert all(group_set["suspended_groups"] == [] for group_set in report["streams"])


def test_suspension_excludes_axles_from_balance_grading_counts_but_keeps_rows():
    axes = [
        _axis("0007/A01", 3000, 2000),
        _axis("0007/A02", 3000, 2000),
        _axis("0007/A03", 2000, 2000),
    ]
    suspended = set(review(_rows(axes), axes)["suspended_axis_ids"])
    graded = balance(axes, suspended)
    assert graded["counts"] == {"pass": 1, "warn": 0, "severe": 0}
    assert {(row["id"], row["level"], row["trusted"]) for row in graded["rows"]} == {
        ("0007/A01", "severe", False),
        ("0007/A02", "severe", False),
        ("0007/A03", "pass", True),
    }


def test_recompute_is_deterministic_and_registers_no_duplicate_suspect(dirty):
    from app.modules.m7_batches.pipeline import run_pipeline

    first = run_pipeline(dirty)
    second = run_pipeline(dirty)
    assert first["drift"] == second["drift"]
    assert first["balance"] == second["balance"]
    assert first["reconcile"] == second["reconcile"]
    assert len(second["drift"]["suspects"]) == 1


def test_reconcile_defaults_hold_back_no_axle_weight(dirty_result):
    ledger = dirty_result["reconcile"]["ledger"]
    # 未受疑漂影响的车次不产生暂扣轮载。
    untouched = [
        row for row in dirty_result["reconcile"]["rows"]
        if row["pass_id"] != "0007"
    ]
    assert all(row["held_kg"] == "0.00" and not row["drift_refs"] for row in untouched)
    assert ledger["suspended_axes"] == 2
