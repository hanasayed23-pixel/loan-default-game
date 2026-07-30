"""
hypothesis_engine.py
Core statistics for the Loan Officer Vignette Experiment (2x2 within-subject).

Maps the collected decision data onto the three proposal hypotheses:
  H1  Credit score main effect
  H2  Stated loan-purpose main effect (productive vs personal use)
  H3  Credit-score dominance when the two signals conflict

Inference method: exact / Monte-Carlo randomisation (permutation) tests under the
sharp null, permuting factor labels WITHIN each participant. This is valid for
very small samples and requires no asymptotic assumptions - appropriate here
because the design has only 4 participants (4 clusters), where mixed-effects
logit standard errors and cluster-robust standard errors are not trustworthy.
"""

from itertools import combinations

import numpy as np
import pandas as pd

RNG_SEED = 20260730
N_PERM = 20000


# ----------------------------------------------------------------------------
# Data preparation
# ----------------------------------------------------------------------------

REQUIRED = ["participant_id", "credit_score_level", "use_of_funds", "decision"]


def load_and_prepare(csv_paths):
    """Read one or more decision-level CSVs and return a tidy dataframe."""
    frames = []
    for p in csv_paths:
        df = pd.read_csv(p)
        df.columns = [c.strip().lower() for c in df.columns]
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)

    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(
            "The data file is missing required column(s): "
            + ", ".join(missing)
            + "\nColumns found: "
            + ", ".join(df.columns)
        )

    # Binary outcome: 1 = approve, 0 = reject
    df["approve"] = (
        df["decision"].astype(str).str.strip().str.lower().isin(["approve", "approved", "1", "yes", "true"])
    ).astype(int)

    # Binary factor codings
    df["score_high"] = (
        df["credit_score_level"].astype(str).str.strip().str.lower().eq("high")
    ).astype(int)
    df["use_productive"] = (
        df["use_of_funds"].astype(str).str.strip().str.lower().str.startswith("prod")
    ).astype(int)
    df["participant_id"] = df["participant_id"].astype(str)

    for col in ("credit_score", "repayment_probability", "business_success_probability"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "round_index" in df.columns:
        df["round_index"] = pd.to_numeric(df["round_index"], errors="coerce")

    return df.sort_values(["participant_id", "round_index"] if "round_index" in df.columns
                          else ["participant_id"]).reset_index(drop=True)


# ----------------------------------------------------------------------------
# Within-participant effect sizes
# ----------------------------------------------------------------------------

def participant_effects(df):
    """Per-participant within-subject differences in approval rate."""
    rows = []
    for pid, g in df.groupby("participant_id"):
        d_score = g.loc[g.score_high == 1, "approve"].mean() - g.loc[g.score_high == 0, "approve"].mean()
        d_use = g.loc[g.use_productive == 1, "approve"].mean() - g.loc[g.use_productive == 0, "approve"].mean()
        rows.append(
            {
                "participant_id": pid,
                "n_decisions": len(g),
                "overall_approval_rate": g["approve"].mean(),
                "effect_credit_score_H1": d_score,
                "effect_loan_purpose_H2": d_use,
                "dominance_gap_H3": d_score - d_use,
            }
        )
    out = pd.DataFrame(rows)
    return out


def cell_means(df):
    """Approval rate in each of the four design cells."""
    g = df.groupby(["credit_score_level", "use_of_funds"], dropna=False)
    out = g.agg(
        n=("approve", "size"),
        n_approved=("approve", "sum"),
        approval_rate=("approve", "mean"),
    ).reset_index()
    for col, label in (
        ("repayment_probability", "mean_estimated_repayment_probability"),
        ("business_success_probability", "mean_estimated_business_success_probability"),
    ):
        if col in df.columns:
            means = g[col].mean().reset_index(name=label)
            out = out.merge(means, on=["credit_score_level", "use_of_funds"], how="left")
    return out.sort_values(["credit_score_level", "use_of_funds"]).reset_index(drop=True)


# ----------------------------------------------------------------------------
# Randomisation inference
# ----------------------------------------------------------------------------

def _participant_avg_diff(y, labels, pid_index):
    """Participant-averaged difference in means between label==1 and label==0."""
    diffs = []
    for idx in pid_index:
        yy, ll = y[idx], labels[idx]
        if ll.sum() == 0 or ll.sum() == len(ll):
            continue
        diffs.append(yy[ll == 1].mean() - yy[ll == 0].mean())
    return float(np.mean(diffs)) if diffs else np.nan


def permutation_test(df, factor_col, n_perm=N_PERM, seed=RNG_SEED):
    """
    Two-sided randomisation test of the sharp null that `factor_col` has no
    effect on the approval decision. Labels are permuted within participant,
    preserving each participant's number of high/low exposures.
    """
    rng = np.random.default_rng(seed)
    y = df["approve"].to_numpy()
    labels = df[factor_col].to_numpy()
    pid_index = [np.flatnonzero(df["participant_id"].to_numpy() == p)
                 for p in df["participant_id"].unique()]

    observed = _participant_avg_diff(y, labels, pid_index)

    count = 0
    for _ in range(n_perm):
        perm = labels.copy()
        for idx in pid_index:
            perm[idx] = rng.permutation(labels[idx])
        stat = _participant_avg_diff(y, perm, pid_index)
        if not np.isnan(stat) and abs(stat) >= abs(observed) - 1e-12:
            count += 1
    p = (count + 1) / (n_perm + 1)
    return {"statistic": observed, "p_value": p, "n_perm": n_perm, "method": "Monte-Carlo randomisation (within participant)"}


def conflict_cell_test(df):
    """
    H3 direct test. Compares the two CONFLICT cells:
        A = High credit score + Non-productive use   (score says yes, capacity says no)
        B = Low  credit score + Productive use       (capacity says yes, score says no)
    If credit score dominates, approval(A) > approval(B).

    With 2 observations per participant in each cell, the randomisation
    distribution is enumerated EXACTLY: C(4,2)=6 relabelings per participant.
    """
    sub = df[
        ((df.score_high == 1) & (df.use_productive == 0))
        | ((df.score_high == 0) & (df.use_productive == 1))
    ].copy()
    sub["in_A"] = ((sub.score_high == 1) & (sub.use_productive == 0)).astype(int)

    per_participant = []
    for pid, g in sub.groupby("participant_id"):
        a = g.loc[g.in_A == 1, "approve"]
        b = g.loc[g.in_A == 0, "approve"]
        per_participant.append(
            {
                "participant_id": pid,
                "n_A_high_score_nonproductive": len(a),
                "approval_A_high_score_nonproductive": a.mean() if len(a) else np.nan,
                "approval_B_low_score_productive": b.mean() if len(b) else np.nan,
                "difference_A_minus_B": (a.mean() - b.mean()) if len(a) and len(b) else np.nan,
            }
        )
    pp = pd.DataFrame(per_participant)
    observed = float(pp["difference_A_minus_B"].mean())

    # Exact enumeration of the null distribution
    groups = []
    for _, g in sub.groupby("participant_id"):
        yy = g["approve"].to_numpy()
        ll = g["in_A"].to_numpy()
        k = int(ll.sum())
        opts = []
        for combo in combinations(range(len(yy)), k):
            lab = np.zeros(len(yy), dtype=int)
            lab[list(combo)] = 1
            if lab.sum() == 0 or lab.sum() == len(lab):
                continue
            opts.append(yy[lab == 1].mean() - yy[lab == 0].mean())
        groups.append(opts)

    # Cartesian product of per-participant options -> exact null distribution
    null = np.array([0.0])
    for opts in groups:
        null = (null[:, None] + np.array(opts)[None, :]).ravel()
    null = null / len(groups)
    p = float(np.mean(np.abs(null) >= abs(observed) - 1e-12))

    return {
        "per_participant": pp,
        "statistic": observed,
        "p_value": p,
        "n_enumerated": int(null.size),
        "method": "Exact randomisation test (full enumeration)",
    }


# ----------------------------------------------------------------------------
# Linear probability model with participant fixed effects + Wald test
# ----------------------------------------------------------------------------

def lpm_with_wald(df):
    """
    OLS linear probability model:
        approve = participant FE + b1*score_high + b2*use_productive
    Wald test of the H3 restriction b1 = b2 (credit-score dominance).
    Reported for continuity with the proposal; the randomisation tests above are
    the primary inference given only 4 participants.
    """
    pids = sorted(df["participant_id"].unique())
    D = np.column_stack([(df["participant_id"] == p).astype(float) for p in pids])
    X = np.column_stack([D, df["score_high"], df["use_productive"]]).astype(float)
    y = df["approve"].to_numpy(dtype=float)

    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    resid = y - X @ beta
    n, k = X.shape
    dof = max(n - k, 1)
    sigma2 = float(resid @ resid) / dof
    V = sigma2 * XtX_inv
    se = np.sqrt(np.diag(V))

    names = [f"FE_participant_{p}" for p in pids] + [
        "credit_score_high_H1",
        "use_productive_H2",
    ]
    coefs = pd.DataFrame({"term": names, "coefficient": beta, "std_error": se})
    coefs["t_stat"] = coefs["coefficient"] / coefs["std_error"].replace(0, np.nan)

    # Wald test: b1 - b2 = 0
    R = np.zeros(k)
    R[len(pids)] = 1.0
    R[len(pids) + 1] = -1.0
    diff = float(R @ beta)
    var_diff = float(R @ V @ R)
    wald = diff**2 / var_diff if var_diff > 0 else np.nan

    # F(1, dof) p-value via the survival function of the F distribution,
    # computed from the incomplete beta function to avoid a scipy dependency.
    p_wald = _f_sf(wald, 1, dof) if np.isfinite(wald) else np.nan

    return {
        "coefficients": coefs,
        "r_squared": 1 - float(resid @ resid) / float(((y - y.mean()) ** 2).sum()),
        "n_obs": n,
        "wald_statistic": wald,
        "wald_p_value": p_wald,
        "beta_score_minus_beta_use": diff,
        "dof": dof,
    }


def _betacf(a, b, x, itmax=200, eps=3e-16):
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < 1e-300:
        d = 1e-300
    d = 1.0 / d
    h = d
    for m in range(1, itmax + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-300:
            d = 1e-300
        c = 1.0 + aa / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-300:
            d = 1e-300
        c = 1.0 + aa / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _betai(a, b, x):
    """Regularised incomplete beta function I_x(a,b)."""
    from math import exp, lgamma
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = lgamma(a + b) - lgamma(a) - lgamma(b) + a * np.log(x) + b * np.log(1.0 - x)
    bt = exp(lbeta)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def _f_sf(f, d1, d2):
    """Upper-tail p-value of the F(d1, d2) distribution."""
    if f <= 0:
        return 1.0
    return float(_betai(d2 / 2.0, d1 / 2.0, d2 / (d2 + d1 * f)))


# ----------------------------------------------------------------------------
# Headline hypothesis table
# ----------------------------------------------------------------------------

def hypothesis_table(df, h1, h2, h3_conflict, eff, lpm):
    n_part = eff.shape[0]
    same_dir_h1 = int((eff["effect_credit_score_H1"] > 0).sum())
    same_dir_h2 = int((eff["effect_loan_purpose_H2"] > 0).sum())
    same_dir_h3 = int((eff["dominance_gap_H3"] > 0).sum())

    def verdict(stat, p, direction_count, expected_sign=1):
        if np.isnan(stat):
            return "Not estimable"
        signed_ok = (stat > 0) if expected_sign > 0 else (stat < 0)
        if not signed_ok:
            return "Not supported - effect runs opposite to prediction"
        if p < 0.05:
            return "Supported (p < 0.05)"
        if p < 0.10:
            return "Directionally supported (p < 0.10)"
        if direction_count == n_part:
            return "Directionally supported - consistent in all participants, not significant"
        return "Not supported at conventional levels"

    rows = [
        {
            "Hypothesis": "H1",
            "Statement": "Applicants with a high credit score are approved more often than those with a low credit score.",
            "Test": "Randomisation test on within-participant difference in approval rate (High - Low)",
            "Effect (pp)": 100 * h1["statistic"],
            "p-value": h1["p_value"],
            "Participants showing predicted direction": f"{same_dir_h1} of {n_part}",
            "Conclusion": verdict(h1["statistic"], h1["p_value"], same_dir_h1),
        },
        {
            "Hypothesis": "H2",
            "Statement": "Applicants with a productive, income-generating stated purpose are approved more often than applicants with a personal stated purpose.",
            "Test": "Randomisation test on within-participant difference in approval rate (Productive - Non-productive)",
            "Effect (pp)": 100 * h2["statistic"],
            "p-value": h2["p_value"],
            "Participants showing predicted direction": f"{same_dir_h2} of {n_part}",
            "Conclusion": verdict(h2["statistic"], h2["p_value"], same_dir_h2),
        },
        {
            "Hypothesis": "H3",
            "Statement": "When the two signals conflict, credit score dominates prospective repayment capacity.",
            "Test": "Exact randomisation test on the conflict cells: (High score + Non-productive) - (Low score + Productive)",
            "Effect (pp)": 100 * h3_conflict["statistic"],
            "p-value": h3_conflict["p_value"],
            "Participants showing predicted direction": f"{same_dir_h3} of {n_part}",
            "Conclusion": verdict(h3_conflict["statistic"], h3_conflict["p_value"], same_dir_h3),
        },
    ]
    t = pd.DataFrame(rows)
    t["Effect (pp)"] = t["Effect (pp)"].round(1)
    t["p-value"] = t["p-value"].round(4)
    return t


def reasons_table(df):
    if "reason_choice" not in df.columns:
        return pd.DataFrame({"note": ["Column 'reason_choice' not present in the data."]})
    r = (
        df["reason_choice"].astype(str).str.strip()
        .value_counts()
        .rename_axis("Most important factor (self-reported)")
        .reset_index(name="Times chosen")
    )
    r["Share of decisions"] = (r["Times chosen"] / r["Times chosen"].sum()).round(3)
    return r


def learning_table(df):
    """Does the purpose effect fade as participants receive outcome feedback?"""
    if "round_index" not in df.columns or df["round_index"].isna().all():
        return pd.DataFrame({"note": ["Column 'round_index' not present in the data."]})
    d = df.dropna(subset=["round_index"]).copy()
    d["half"] = np.where(d["round_index"] <= 4, "Rounds 1-4 (early)", "Rounds 5-8 (late)")
    rows = []
    for half, g in d.groupby("half"):
        rows.append(
            {
                "Block": half,
                "n_decisions": len(g),
                "Credit-score effect (pp)": round(
                    100 * (g.loc[g.score_high == 1, "approve"].mean() - g.loc[g.score_high == 0, "approve"].mean()), 1
                ),
                "Repayment-capacity effect (pp)": round(
                    100 * (g.loc[g.use_productive == 1, "approve"].mean() - g.loc[g.use_productive == 0, "approve"].mean()), 1
                ),
                "Overall approval rate": round(g["approve"].mean(), 3),
            }
        )
    return pd.DataFrame(rows).sort_values("Block").reset_index(drop=True)
