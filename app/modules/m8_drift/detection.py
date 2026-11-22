from collections import defaultdict

from app.config import DRIFT_MIN_RUN


def detect(balance_rows, axes, min_run=DRIFT_MIN_RUN):
    """按车次识别同轮道连续偏重的疑漂序列。

    只在已确认且已判级的车轴上判定：重侧相同的 warn/severe 车轴连续达到
    ``min_run`` 根才成疑。单轴偏重、对侧交替偏重或正常轴都会打断序列，
    因此不会因为一次真实偏载就停用整条轮道。
    """
    groups = defaultdict(set)
    for axis in axes:
        groups[axis["pass_id"]].add(axis["group"])

    by_pass = defaultdict(list)
    for row in balance_rows:
        by_pass[row["pass_id"]].append(row)

    streams, suspects, suspended_ids = [], [], set()
    for pass_id in sorted(by_pass):
        rows = by_pass[pass_id]
        run = []

        def close(candidates):
            if len(candidates) < min_run:
                return
            side = candidates[0]["heavy"]
            ids = [item["id"] for item in candidates]
            suspended_ids.update(ids)
            affected_groups = sorted({next(a["group"] for a in axes if a["id"] == item["id"]) for item in candidates})
            for group in affected_groups:
                groups[pass_id].discard(group)
            refs = tuple(dict.fromkeys(
                ref for item in candidates for ref in (
                    item["left_ref"] if side == "L" else item["right_ref"],
                )
            ))
            opposite_refs = tuple(dict.fromkeys(
                ref for item in candidates for ref in (
                    item["right_ref"] if side == "L" else item["left_ref"],
                )
            ))
            suspects.append({
                "pass_id": pass_id,
                "side": side,
                "lane": "左" if side == "L" else "右",
                "axis_ids": ids,
                "groups": affected_groups,
                "min_run": min_run,
                "levels": [item["level"] for item in candidates],
                "percents": [item["percent"] for item in candidates],
                "drift_refs": refs,
                "opposite_refs": opposite_refs,
                "basis": (
                    f"同车次 {len(candidates)} 根车轴连续{('左' if side == 'L' else '右')}偏重"
                    f"（偏载率 {'/'.join(str(item['percent']) for item in candidates)}%），"
                    "达到疑漂连续轴数；同组对侧轮道仅作对照，不能单独证明轮道正常。"
                ),
            })

        for row in rows:
            if row["level"] in {"warn", "severe"} and row["heavy"] and (
                not run or row["heavy"] == run[0]["heavy"]
            ):
                run.append(row)
            else:
                close(run)
                run = []
        close(run)

        streams.append({
            "pass_id": pass_id,
            "trusted_groups": sorted(groups[pass_id]),
            "suspended_groups": sorted(
                {group for suspect in suspects if suspect["pass_id"] == pass_id for group in suspect["groups"]}
            ),
        })

    return {
        "suspects": suspects,
        "streams": streams,
        "suspended_axis_ids": sorted(suspended_ids),
        "min_run": min_run,
        "counts": {
            "suspect_lanes": len({(item["pass_id"], item["side"]) for item in suspects}),
            "suspended_axes": len(suspended_ids),
            "suspended_groups": len({
                (item["pass_id"], group) for item in suspects for group in item["groups"]
            }),
        },
    }
