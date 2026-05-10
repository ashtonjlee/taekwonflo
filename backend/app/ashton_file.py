"""
tournament_scheduler.py
══════════════════════════════════════════════════════════════════════════════
Standalone CP-SAT scheduler for multi-mat tournament scheduling.

What it does
────────────
Given a set of matches (sparring and/or poomsae) it assigns each match a
mat and a start time such that:

  • No two matches overlap on the same mat
  • Bracket precedence is respected (a semi-final can't start before its
    quarter-finals finish, with a configurable athlete rest gap)
  • Referee capacity is respected across all mats simultaneously
  • Automatic ref-break windows are injected every 2 hours (configurable)
  • All poomsae finishes before sparring begins (hard constraint)
  • Objective: minimise makespan → then penalise long division spans →
    then reward early finish for younger age groups

Dependencies
────────────
    pip install ortools

Quick start
────────────
    from tournament_scheduler import SchedulerConfig, Match, schedule

    cfg = SchedulerConfig(num_mats=5, total_refs=30, day_start=480)

    matches = {
        "SP_001": Match(id="SP_001", division_id="DIV_A", event="sparring",
                        belt="Black", round_num=1, total_rounds=2,
                        predecessors=[], duration_min=13),
        "SP_002": Match(id="SP_002", division_id="DIV_A", event="sparring",
                        belt="Black", round_num=2, total_rounds=2,
                        predecessors=["SP_001"], duration_min=13),
        "PO_001": Match(id="PO_001", division_id="DIV_B", event="poomsae",
                        belt="Red", round_num=1, total_rounds=1,
                        predecessors=[], duration_min=6),
    }

    # divisions tell the solver which match_ids belong to each division
    divisions = [
        {"id": "DIV_A", "match_ids": ["SP_001", "SP_002"],
         "age_group": "Senior", "label": "Senior Black Men Sparring"},
        {"id": "DIV_B", "match_ids": ["PO_001"],
         "age_group": "Junior", "label": "Junior Red Mixed Poomsae"},
    ]

    result = schedule(sparring_matches={"SP_001": matches["SP_001"],
                                        "SP_002": matches["SP_002"]},
                      poomsae_matches={"PO_001": matches["PO_001"]},
                      sparring_divs=divisions[:1],
                      poomsae_divs=divisions[1:],
                      cfg=cfg)

    for mid, sm in result.items():
        print(sm)
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from ortools.sat.python import cp_model


# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SchedulerConfig:
    """
    All knobs for the CP-SAT scheduler.

    Parameters
    ──────────
    num_mats : int
        Total number of mats/rings.  All are treated as identical.
    total_refs : int
        Total referee headcount available across all mats simultaneously.
    day_start : int
        Tournament start time in minutes from midnight.  480 = 08:00.
    athlete_rest_min : int
        Minimum gap (minutes) an athlete must have between their own
        consecutive matches (enforced via bracket predecessor constraints).
    refs_sparring_black : int
        Referees consumed by a single black-belt sparring match.
    refs_sparring_color : int
        Referees consumed by a single color-belt sparring match.
    refs_poomsae_black_early : int
        Referees consumed by a black-belt poomsae match before semis.
    refs_poomsae_black_late : int
        Referees consumed by a black-belt poomsae semi / final.
    refs_poomsae_color : int
        Referees consumed by a color-belt poomsae match.
    solver_time_limit : float
        CP-SAT wall-clock time limit in seconds.
    num_search_workers : int
        Parallel search threads for CP-SAT.
    span_threshold_min : int
        Divisions whose matches span more than this many minutes are
        penalised by the secondary objective.
    ag_finish_weights : dict[str, int]
        Objective weight for finishing each age group early.  Higher →
        stronger pull.  The solver trades at most w/10000 minutes of
        makespan to save 1 minute on that group's last match.
    ref_break_short_min : int
        Duration (minutes) of a regular referee break.
    ref_break_long_min : int
        Duration (minutes) of the single long (lunch) break.
    ref_break_interval_min : int
        How often (minutes) a referee break is scheduled.
    ref_break_lunch_after_min : int
        Promote the first break at or after this offset to a long break.
    """

    # ── Physical setup ────────────────────────────────────────────────────────
    num_mats:           int   = 5
    total_refs:         int   = 30
    day_start:          int   = 480       # 08:00

    # ── Athlete rest ──────────────────────────────────────────────────────────
    athlete_rest_min:   int   = 10

    # ── Referee demand per match type ─────────────────────────────────────────
    refs_sparring_black:      int = 4
    refs_sparring_color:      int = 5
    refs_poomsae_black_early: int = 3
    refs_poomsae_black_late:  int = 5
    refs_poomsae_color:       int = 3

    # ── Solver ────────────────────────────────────────────────────────────────
    solver_time_limit:  float = 60.0
    num_search_workers: int   = 8

    # ── Objective tuning ─────────────────────────────────────────────────────
    span_threshold_min: int = 90
    ag_finish_weights: dict = field(default_factory=lambda: {
        "Dragon": 1000, "Tiger": 750,
        "Youth":  500,  "Cadet": 350, "Junior": 200,
    })

    # ── Ref-break schedule ────────────────────────────────────────────────────
    ref_break_short_min:       int = 15
    ref_break_long_min:        int = 30
    ref_break_interval_min:    int = 120
    ref_break_lunch_after_min: int = 240   # promote first break ≥ 4 h to lunch

    # ── Helpers ───────────────────────────────────────────────────────────────

    def refs_for(self, belt: str, event: str,
                 round_num: int, total_rounds: int) -> int:
        """Return referee demand for a single match."""
        if event == "poomsae":
            if belt == "Black" and round_num >= total_rounds - 1:
                return self.refs_poomsae_black_late
            return (self.refs_poomsae_color
                    if belt != "Black"
                    else self.refs_poomsae_black_early)
        return (self.refs_sparring_black
                if belt == "Black"
                else self.refs_sparring_color)

    @staticmethod
    def fmt(minutes: int) -> str:
        """Format minutes-from-midnight as HH:MM."""
        h, m = divmod(int(minutes), 60)
        return f"{h}:{m:02d}"


# ═══════════════════════════════════════════════════════════════════════════════
#  DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Match:
    """
    A single schedulable match.

    Attributes
    ──────────
    id : str
        Unique identifier, e.g. "SP_DIV_A_r1p0".
    division_id : str
        ID of the parent division (used for span & age-group objectives).
    event : str
        "sparring" or "poomsae".
    belt : str
        Belt category: "Black", "Red", "Blue", "Green", "White/Yellow".
    round_num : int
        Round number within the bracket (1 = first round).
    total_rounds : int
        Total rounds in the bracket (ceil(log2(num_athletes))).
    predecessors : list[str]
        IDs of matches that must finish before this one can start
        (i.e. whose winner feeds into this match).
    duration_min : int
        Expected duration of this match in whole minutes.
    label : str
        Human-readable label (used in output only).
    """

    id:            str
    division_id:   str
    event:         str          # "sparring" | "poomsae"
    belt:          str
    round_num:     int
    total_rounds:  int
    predecessors:  list = field(default_factory=list)
    duration_min:  int  = 6
    label:         str  = ""


@dataclass
class ScheduledMatch:
    """
    The result of scheduling one match.

    Attributes
    ──────────
    match_id : str
    division_id : str
    div_label : str
    event : str
    belt : str
    round_num, total_rounds : int
    mat : int
        1-indexed mat / ring assignment.
    start_abs, end_abs : int
        Absolute start and end times in minutes from midnight.
    match_num : int, optional
        Assigned after scheduling (see assign_match_numbers()).
    """

    match_id:     str
    division_id:  str
    div_label:    str
    event:        str
    belt:         str
    round_num:    int
    total_rounds: int
    mat:          int
    start_abs:    int
    end_abs:      int
    match_num:    Optional[int] = None

    @property
    def start_str(self) -> str:
        return SchedulerConfig.fmt(self.start_abs)

    @property
    def end_str(self) -> str:
        return SchedulerConfig.fmt(self.end_abs)

    @property
    def round_label(self) -> str:
        names = {1: "Final", 2: "Semifinals", 3: "Quarterfinals",
                 4: "Round of 16", 5: "Round of 32"}
        return names.get(self.total_rounds - self.round_num + 1,
                         f"Round {self.round_num}")

    def __repr__(self) -> str:
        num = f"#{self.match_num} " if self.match_num else ""
        return (f"ScheduledMatch({num}mat={self.mat} "
                f"{self.start_str}–{self.end_str} "
                f"[{self.event}/{self.belt}] {self.division_id})")


# ═══════════════════════════════════════════════════════════════════════════════
#  CORE SCHEDULER
# ═══════════════════════════════════════════════════════════════════════════════

def schedule(
    sparring_matches: dict[str, Match],
    poomsae_matches:  dict[str, Match],
    sparring_divs:    list[dict],
    poomsae_divs:     list[dict],
    cfg:              SchedulerConfig,
) -> dict[str, ScheduledMatch]:
    """
    Schedule all matches using CP-SAT (Flexible Job Shop variant).

    Parameters
    ──────────
    sparring_matches : dict[match_id → Match]
        All sparring matches to schedule.
    poomsae_matches : dict[match_id → Match]
        All poomsae matches to schedule.
    sparring_divs : list of division dicts
        Each dict must have at least: {"id": str, "match_ids": [str, ...],
        "age_group": str, "label": str}.
    poomsae_divs : list of division dicts
        Same structure as sparring_divs.
    cfg : SchedulerConfig
        All configuration knobs (mats, refs, time limit, etc.).

    Returns
    ───────
    dict[match_id → ScheduledMatch]
        Empty dict if no feasible solution is found within the time limit.

    Constraints (hard)
    ──────────────────
    1. No two matches overlap on the same mat.
    2. Bracket predecessor + athlete rest gap:
           start[m] ≥ end[pred] + cfg.athlete_rest_min  for each predecessor
    3. Cumulative ref capacity:
           Σ refs_for(running matches at time t) ≤ cfg.total_refs  ∀ t
       Automatic break windows reduce effective capacity by `surplus` refs
       every cfg.ref_break_interval_min minutes so refs can rotate off.
    4. Poomsae-first:
           start[sparring_m] ≥ max(end[poomsae_m])  for all m

    Objective (minimise, lexicographic via integer weights)
    ───────────────────────────────────────────────────────
      10 000 × makespan
    +    100 × Σ max(0, span(div) − cfg.span_threshold_min)
    +      1 × Σ w_ag × last_end(age_group_division)   [age-group finish]
    +      1 × Σ start_times                            [pack matches early]
    """

    model = cp_model.CpModel()
    K     = cfg.num_mats
    all_m = {**sparring_matches, **poomsae_matches}

    if not all_m:
        return {}

    # ── Horizon ───────────────────────────────────────────────────────────────
    # Wall-clock upper bound: serial work spread across K mats + 50% slack +
    # break padding.  Capped at 840 min (14 h) to keep break-window generation
    # and variable domains tractable.
    serial_work = sum(m.duration_min for m in all_m.values())
    H = min(int(serial_work / max(K, 1) * 1.5) + 240, 840)

    # ── Decision variables ────────────────────────────────────────────────────
    start_v:  dict[str, cp_model.IntVar]                  = {}
    end_v:    dict[str, cp_model.IntVar]                  = {}
    perf:     dict[str, dict[int, cp_model.BoolVar]]      = {}
    opt_ivs:  dict[str, dict[int, cp_model.IntervalVar]]  = {}
    glob_ivs:  list = []
    glob_dmds: list = []

    for mid, m in all_m.items():
        dur = m.duration_min
        s   = model.NewIntVar(0, H, f"s_{mid}")
        e   = model.NewIntVar(0, H, f"e_{mid}")
        model.Add(e == s + dur)
        start_v[mid] = s
        end_v[mid]   = e

        perf[mid]    = {}
        opt_ivs[mid] = {}

        for k in range(K):
            b  = model.NewBoolVar(f"p_{mid}_{k}")
            iv = model.NewOptionalIntervalVar(s, dur, e, b, f"i_{mid}_{k}")
            perf[mid][k]    = b
            opt_ivs[mid][k] = iv

        # Every match is assigned to exactly one mat
        model.AddExactlyOne([perf[mid][k] for k in range(K)])

        # Global interval for the cumulative ref-demand constraint
        glob_ivs.append(model.NewIntervalVar(s, dur, e, f"g_{mid}"))
        glob_dmds.append(
            cfg.refs_for(m.belt, m.event, m.round_num, m.total_rounds)
        )

    # ── No-overlap per mat ────────────────────────────────────────────────────
    for k in range(K):
        model.AddNoOverlap([opt_ivs[mid][k] for mid in all_m])

    # ── Bracket precedence + athlete rest gap ─────────────────────────────────
    for mid, m in all_m.items():
        for pred_id in m.predecessors:
            if pred_id in all_m:
                model.Add(
                    start_v[mid] >= end_v[pred_id] + cfg.athlete_rest_min
                )

    # ── Automatic ref-break windows ───────────────────────────────────────────
    # Refs rotate in groups; during each break the effective capacity drops by
    # `surplus` so the refs can step off without stopping every mat.
    peak_demand = K * cfg.refs_sparring_black           # worst-case simultaneous load
    surplus     = max(1, cfg.total_refs - peak_demand)  # refs that can rotate off

    ref_break_ivs:  list = []
    ref_break_dmds: list = []
    lunch_done = False
    t = cfg.ref_break_interval_min

    while t < H - cfg.ref_break_short_min:
        is_lunch   = (not lunch_done and t >= cfg.ref_break_lunch_after_min)
        dur        = cfg.ref_break_long_min if is_lunch else cfg.ref_break_short_min
        lunch_done = lunch_done or is_lunch

        s_c = model.NewConstant(t)
        e_c = model.NewConstant(t + dur)
        iv  = model.NewIntervalVar(s_c, dur, e_c,
                                   f"ref_brk_{len(ref_break_ivs)}")
        ref_break_ivs.append(iv)
        ref_break_dmds.append(surplus)
        t += cfg.ref_break_interval_min + dur

    model.AddCumulative(
        glob_ivs  + ref_break_ivs,
        glob_dmds + ref_break_dmds,
        cfg.total_refs,
    )

    # ── Hard poomsae-first constraint ─────────────────────────────────────────
    # All sparring starts after all poomsae ends.
    po_global_end = model.NewIntVar(0, H, "po_global_end")
    if poomsae_matches:
        model.AddMaxEquality(
            po_global_end, [end_v[mid] for mid in poomsae_matches]
        )
        for smid in sparring_matches:
            model.Add(start_v[smid] >= po_global_end)
    else:
        model.Add(po_global_end == 0)

    # ── Division span penalty + age-group finish reward ───────────────────────
    all_divs = (
        {d["id"]: d for d in sparring_divs}
        | {d["id"]: d for d in poomsae_divs}
    )

    excess_spans:    list[cp_model.IntVar] = []
    age_finish_vars: list[cp_model.IntVar] = []
    age_finish_wts:  list[int]             = []

    for did, div in all_divs.items():
        mids = [mid for mid in div.get("match_ids", []) if mid in all_m]
        if not mids:
            continue

        ag = div.get("age_group", "")
        le = model.NewIntVar(0, H, f"le_{did}")
        model.AddMaxEquality(le, [end_v[mid] for mid in mids])

        # Age-group finish reward (younger brackets finish earlier)
        w = cfg.ag_finish_weights.get(ag, 0)
        if w:
            age_finish_vars.append(le)
            age_finish_wts.append(w)

        # Span penalty (divisions with ≥2 matches)
        if len(mids) >= 2:
            fs   = model.NewIntVar(0, H, f"fs_{did}")
            span = model.NewIntVar(0, H, f"span_{did}")
            model.AddMinEquality(fs, [start_v[mid] for mid in mids])
            model.Add(span == le - fs)
            excess = model.NewIntVar(0, H, f"exc_{did}")
            model.AddMaxEquality(
                excess,
                [span - cfg.span_threshold_min, model.NewConstant(0)]
            )
            excess_spans.append(excess)

    # ── Objective ─────────────────────────────────────────────────────────────
    makespan = model.NewIntVar(0, H, "makespan")
    model.AddMaxEquality(makespan, [end_v[mid] for mid in all_m])

    total_excess = (cp_model.LinearExpr.Sum(excess_spans)
                    if excess_spans else model.NewConstant(0))
    age_obj      = (cp_model.LinearExpr.WeightedSum(age_finish_vars, age_finish_wts)
                    if age_finish_vars else model.NewConstant(0))
    total_starts = cp_model.LinearExpr.Sum(list(start_v.values()))

    model.Minimize(
        10_000 * makespan
        +    100 * total_excess
        +      1 * age_obj
        +      1 * total_starts
    )

    # ── Solve ─────────────────────────────────────────────────────────────────
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = cfg.solver_time_limit
    solver.parameters.num_search_workers  = cfg.num_search_workers
    solver.parameters.log_search_progress = False

    n_breaks = len(ref_break_ivs)
    print(f"  Solving: {len(all_m)} matches | {K} mats | {n_breaks} ref-break windows")

    status = solver.Solve(model)
    stat   = solver.StatusName(status)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print(f"  ❌ CP-SAT status: {stat}")
        return {}

    finish = cfg.day_start + solver.Value(makespan)
    po_end = cfg.day_start + solver.Value(po_global_end)
    print(f"  Status:        {stat}")
    print(f"  Finish time:   {SchedulerConfig.fmt(finish)}")
    print(f"  Poomsae done:  {SchedulerConfig.fmt(po_end)}")
    print(f"  Sparring from: {SchedulerConfig.fmt(po_end)}")

    # ── Build output ──────────────────────────────────────────────────────────
    result: dict[str, ScheduledMatch] = {}
    for mid, m in all_m.items():
        mat_k = next(k for k in range(K) if solver.Value(perf[mid][k]))
        s_abs = cfg.day_start + solver.Value(start_v[mid])
        e_abs = cfg.day_start + solver.Value(end_v[mid])
        div   = all_divs.get(m.division_id, {})
        result[mid] = ScheduledMatch(
            match_id=mid,
            division_id=m.division_id,
            div_label=div.get("label", m.label or "?"),
            event=m.event,
            belt=m.belt,
            round_num=m.round_num,
            total_rounds=m.total_rounds,
            mat=mat_k + 1,        # 1-indexed
            start_abs=s_abs,
            end_abs=e_abs,
        )

    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  POST-PROCESSING — MATCH NUMBER ASSIGNMENT
# ═══════════════════════════════════════════════════════════════════════════════

def assign_match_numbers(
    schedule_result: dict[str, ScheduledMatch],
    system: str = "mat",
    seq_start: int = 100,
) -> dict[str, ScheduledMatch]:
    """
    Stamp each ScheduledMatch with a human-readable match number.

    system="mat"  (default)
        Match numbers encode the mat:  mat M, ordinal N  →  M*100 + N
        E.g. mat-1 match-3 → #103 ;  mat-2 match-1 → #201
        Ordinals start at 1 (no X00 numbers).
        Warn if any mat has >99 matches (switch to "seq" in that case).

    system="seq"
        Sequential integers starting from seq_start:  100, 101, 102, …

    Modifies ScheduledMatch.match_num in-place and returns the same dict.
    """
    if system == "seq":
        for i, sm in enumerate(
            sorted(schedule_result.values(), key=lambda s: s.start_abs)
        ):
            sm.match_num = seq_start + i
        return schedule_result

    # MAT_BASED
    mat_ordinal: dict[int, int] = defaultdict(int)
    overflow_mats: set[int] = set()
    for sm in sorted(schedule_result.values(),
                     key=lambda s: (s.mat, s.start_abs)):
        mat_ordinal[sm.mat] += 1
        n = mat_ordinal[sm.mat]
        if n > 99:
            overflow_mats.add(sm.mat)
        sm.match_num = sm.mat * 100 + n

    if overflow_mats:
        print(f"  ⚠ Mats {sorted(overflow_mats)} have >99 matches; "
              f"consider system='seq'")

    return schedule_result


# ═══════════════════════════════════════════════════════════════════════════════
#  EXAMPLE / SMOKE TEST
# ═══════════════════════════════════════════════════════════════════════════════

def _build_example() -> tuple[dict, dict, list, list]:
    """
    Tiny synthetic tournament: 3 sparring divisions + 1 poomsae division.
    Returns (sparring_matches, poomsae_matches, sparring_divs, poomsae_divs).
    """
    import math

    def bracket(div_id: str, n: int, event: str, belt: str,
                dur: int) -> tuple[dict, list[str]]:
        """Single-elim bracket for n athletes; returns (matches, match_ids)."""
        num_rounds   = math.ceil(math.log2(max(n, 2)))
        bracket_size = 1 << num_rounds
        # layer tracks match-ids (or None=bye, "A"=athlete slot)
        layer = ["A" if i < n else None for i in range(bracket_size)]
        matches: dict[str, Match] = {}
        for rnd in range(1, num_rounds + 1):
            next_layer = []
            for j in range(len(layer) // 2):
                left, right = layer[2*j], layer[2*j+1]
                if left is None and right is None:
                    next_layer.append(None)
                elif left is None or right is None:
                    next_layer.append(left if right is None else right)
                else:
                    mid   = f"{div_id}_r{rnd}p{j}"
                    preds = [x for x in (left, right) if x != "A"]
                    matches[mid] = Match(
                        id=mid, division_id=div_id, event=event, belt=belt,
                        round_num=rnd, total_rounds=num_rounds,
                        predecessors=preds, duration_min=dur,
                    )
                    next_layer.append(mid)
            layer = next_layer
        return matches, list(matches.keys())

    sp_matches: dict[str, Match] = {}
    po_matches: dict[str, Match] = {}
    sp_divs: list[dict] = []
    po_divs: list[dict] = []

    configs = [
        # (div_id, n_athletes, belt, age_group, dur)
        ("SP_Senior_Black_M",   8, "Black",      "Senior", 13),
        ("SP_Youth_Red_M",      6, "Red",         "Youth",   6),
        ("SP_Cadet_Green_F",    4, "Green",       "Cadet",   6),
    ]
    for did, n, belt, ag, dur in configs:
        m, ids = bracket(did, n, "sparring", belt, dur)
        sp_matches.update(m)
        sp_divs.append({"id": did, "match_ids": ids,
                         "age_group": ag, "label": f"{ag} {belt} Sparring"})

    # One poomsae division (4-person bracket)
    m, ids = bracket("PO_Junior_Black_F", 4, "poomsae", "Black", 6)
    po_matches.update(m)
    po_divs.append({"id": "PO_Junior_Black_F", "match_ids": ids,
                     "age_group": "Junior", "label": "Junior Black Poomsae"})

    return sp_matches, po_matches, sp_divs, po_divs


if __name__ == "__main__":
    print("═" * 60)
    print("  tournament_scheduler — example run")
    print("═" * 60)

    cfg = SchedulerConfig(
        num_mats=5,
        total_refs=30,
        day_start=480,          # 08:00
        solver_time_limit=30.0,
    )

    sp_m, po_m, sp_d, po_d = _build_example()
    print(f"\n  Sparring matches : {len(sp_m)}")
    print(f"  Poomsae  matches : {len(po_m)}\n")

    result = schedule(
        sparring_matches=sp_m,
        poomsae_matches=po_m,
        sparring_divs=sp_d,
        poomsae_divs=po_d,
        cfg=cfg,
    )

    if result:
        assign_match_numbers(result, system="mat")
        print("\n  Schedule (sorted by mat, then time):")
        print(f"  {'Match #':<10} {'Mat':<5} {'Start':<7} {'End':<7} "
              f"{'Event':<10} {'Belt':<14} {'Division'}")
        print("  " + "─" * 75)
        for sm in sorted(result.values(), key=lambda s: (s.mat, s.start_abs)):
            print(f"  #{sm.match_num:<9} {sm.mat:<5} {sm.start_str:<7} "
                  f"{sm.end_str:<7} {sm.event:<10} {sm.belt:<14} "
                  f"{sm.division_id}")
    else:
        print("\n  No feasible schedule found.")