from __future__ import annotations

import json
import math

Vector = list[float]


def validate_distribution(values: Vector) -> None:
    if (
        not values
        or any(not math.isfinite(v) or v < 0 for v in values)
        or not math.isclose(math.fsum(values), 1.0, abs_tol=1e-8)
    ):
        raise ValueError("Expected a finite normalized probability distribution")


def residual_distribution(p: Vector, q: Vector) -> Vector:
    """Compute normalized [p(x) - q(x)]_+ required for lossless speculative rejection sampling."""
    validate_distribution(p)
    validate_distribution(q)
    if len(p) != len(q):
        raise ValueError("Vocabulary sizes differ")
    pos = [max(0.0, pv - qv) for pv, qv in zip(p, q)]
    total = sum(pos)
    if total <= 1e-15:
        return list(p)
    return [val / total for val in pos]


def marginal_output_distribution(
    p: Vector, q: Vector, use_residual: bool = True
) -> Vector:
    """Compute the exact marginal probability P(Y = y) of one speculative verification step."""
    validate_distribution(p)
    validate_distribution(q)
    if len(p) != len(q):
        raise ValueError("Vocabulary sizes differ")
    vocab = len(p)
    accepted_mass = [q[y] * min(1.0, p[y] / max(q[y], 1e-15)) for y in range(vocab)]
    reject_prob = 1.0 - sum(accepted_mass)
    resample_dist = residual_distribution(p, q) if use_residual else p
    return [accepted_mass[y] + reject_prob * resample_dist[y] for y in range(vocab)]


def total_variation_distance(p: Vector, q: Vector) -> float:
    return round(0.5 * sum(abs(pv - qv) for pv, qv in zip(p, q)), 8)


def _sample_from_cdf(dist: Vector, u: float) -> int:
    acc = 0.0
    for idx, prob in enumerate(dist):
        acc += prob
        if u < acc:
            return idx
    return len(dist) - 1


def verify_speculative_draft(
    draft_tokens: list[int],
    draft_probs: list[Vector],
    target_probs: list[Vector],
    uniform_draws: list[float],
    resample_draws: list[float],
    use_residual: bool = True,
) -> dict[str, object]:
    """Verify gamma draft tokens in one target pass using lossless rejection sampling.

    - target_probs has length gamma + 1 (positions 0..gamma-1 plus the bonus position gamma).
    - Returns accepted count, emitted token IDs, and step trace.
    """
    gamma = len(draft_tokens)
    if len(draft_probs) != gamma or len(target_probs) != gamma + 1:
        raise ValueError(
            "target_probs must have length gamma + 1 and draft_probs length gamma"
        )

    if len(uniform_draws) != gamma or len(resample_draws) != gamma + 1:
        raise ValueError("Draw counts do not match draft length")
    if any(not 0 <= draw < 1 for draw in uniform_draws + resample_draws):
        raise ValueError("Draws must be in [0,1)")
    for vector in draft_probs + target_probs:
        validate_distribution(vector)
    width = len(target_probs[0])
    if any(len(vector) != width for vector in draft_probs + target_probs):
        raise ValueError("Vocabulary sizes differ")
    if any(
        not 0 <= token < width or draft_probs[i][token] <= 0
        for i, token in enumerate(draft_tokens)
    ):
        raise ValueError("Draft token must have positive proposal probability")
    emitted: list[int] = []
    trace: list[dict[str, object]] = []
    accepted_draft_tokens = 0

    for i in range(gamma):
        tok = draft_tokens[i]
        p_tok = target_probs[i][tok]
        q_tok = max(draft_probs[i][tok], 1e-12)
        accept_ratio = min(1.0, p_tok / q_tok)
        u = uniform_draws[i]

        if u < accept_ratio:
            emitted.append(tok)
            accepted_draft_tokens += 1
            trace.append(
                {
                    "position": i,
                    "draft_token": tok,
                    "p_target": round(p_tok, 4),
                    "q_draft": round(q_tok, 4),
                    "accept_prob": round(accept_ratio, 4),
                    "u_draw": round(u, 4),
                    "outcome": "accepted",
                    "emitted_token": tok,
                }
            )
        else:
            fallback_dist = (
                residual_distribution(target_probs[i], draft_probs[i])
                if use_residual
                else target_probs[i]
            )
            corrected_tok = _sample_from_cdf(fallback_dist, resample_draws[i])
            emitted.append(corrected_tok)
            trace.append(
                {
                    "position": i,
                    "draft_token": tok,
                    "p_target": round(p_tok, 4),
                    "q_draft": round(q_tok, 4),
                    "accept_prob": round(accept_ratio, 4),
                    "u_draw": round(u, 4),
                    "outcome": "rejected_and_resampled",
                    "emitted_token": corrected_tok,
                }
            )
            return {
                "gamma": gamma,
                "accepted_draft_tokens": accepted_draft_tokens,
                "emitted_tokens": emitted,
                "total_emitted": len(emitted),
                "trace": trace,
            }

    # All gamma draft tokens were accepted; sample one bonus token from target_probs[gamma]
    bonus_tok = _sample_from_cdf(target_probs[gamma], resample_draws[-1])
    emitted.append(bonus_tok)
    trace.append(
        {
            "position": gamma,
            "draft_token": None,
            "outcome": "bonus_token_from_target",
            "emitted_token": bonus_tok,
        }
    )
    return {
        "gamma": gamma,
        "accepted_draft_tokens": accepted_draft_tokens,
        "emitted_tokens": emitted,
        "total_emitted": len(emitted),
        "trace": trace,
    }


def expected_tokens_per_step(alpha: float, gamma: int) -> float:
    """Closed-form expected tokens generated per verification step for acceptance rate alpha."""
    if not (0.0 <= alpha <= 1.0):
        raise ValueError("alpha must be in [0, 1]")
    if gamma <= 0:
        raise ValueError("gamma must be positive")
    if abs(1.0 - alpha) < 1e-9:
        return float(gamma + 1)
    return round((1.0 - (alpha ** (gamma + 1))) / (1.0 - alpha), 4)


def estimate_forward_pass_ms(
    num_active_tokens: int,
    base_weight_read_ms: float,
    compute_ms_per_token: float,
    ridge_tokens: int = 48,
) -> float:
    """Piecewise roofline step time for a target or draft forward pass."""
    extra_tokens = max(0, num_active_tokens - ridge_tokens)
    return round(base_weight_read_ms + extra_tokens * compute_ms_per_token, 4)


def speculative_speedup_by_batch(
    gamma: int = 4,
    alphas: tuple[float, ...] = (0.80, 0.45),
    batch_sizes: tuple[int, ...] = (1, 2, 4, 8, 16, 32, 64),
) -> list[dict[str, object]]:
    """Compare standard target decode vs speculative decoding across batch sizes and acceptance rates."""
    # Target 70B FP8 on 2xH100: 22.0 ms weight load, 0.28 ms/token compute above ridge=48
    # Draft 8B FP8 on 2xH100: 2.6 ms weight load, 0.032 ms/token compute above ridge=48
    rows: list[dict[str, object]] = []
    for b in batch_sizes:
        std_step_ms = estimate_forward_pass_ms(
            num_active_tokens=b,
            base_weight_read_ms=22.0,
            compute_ms_per_token=0.42,
            ridge_tokens=32,
        )
        draft_pass_ms = estimate_forward_pass_ms(
            num_active_tokens=b,
            base_weight_read_ms=2.6,
            compute_ms_per_token=0.045,
            ridge_tokens=32,
        )
        verify_tokens = b * (gamma + 1)
        target_verify_ms = estimate_forward_pass_ms(
            num_active_tokens=verify_tokens,
            base_weight_read_ms=22.0,
            compute_ms_per_token=0.42,
            ridge_tokens=32,
        )
        spec_cycle_ms = round(gamma * draft_pass_ms + target_verify_ms, 2)

        row: dict[str, object] = {
            "batch_size": b,
            "verify_batched_tokens": verify_tokens,
            "standard_decode_ms_per_token": round(std_step_ms, 2),
            "spec_cycle_ms": spec_cycle_ms,
        }
        for alpha in alphas:
            exp_tokens = expected_tokens_per_step(alpha, gamma)
            eff_ms_per_tok = round(spec_cycle_ms / exp_tokens, 2)
            speedup = round(std_step_ms / eff_ms_per_tok, 2)
            tag = f"alpha_{int(alpha * 100)}"
            row[f"{tag}_expected_tokens"] = exp_tokens
            row[f"{tag}_ms_per_token"] = eff_ms_per_tok
            row[f"{tag}_speedup"] = speedup
        rows.append(row)
    return rows


def run_verification_demo() -> dict[str, object]:
    # 4-token vocabulary example over gamma = 4 draft positions
    draft_tokens = [0, 1, 2, 1]
    draft_probs = [
        [0.65, 0.20, 0.10, 0.05],
        [0.10, 0.70, 0.15, 0.05],
        [0.05, 0.15, 0.60, 0.20],
        [0.15, 0.55, 0.20, 0.10],
    ]
    target_probs = [
        [0.70, 0.18, 0.08, 0.04],  # pos 0: p(0)=0.70 >= q(0)=0.65 -> accept_prob = 1.0
        [0.12, 0.68, 0.14, 0.06],  # pos 1: p(1)=0.68, q(1)=0.70 -> accept_prob = 0.9714
        [
            0.10,
            0.48,
            0.18,
            0.24,
        ],  # pos 2: p(2)=0.18 < q(2)=0.60 -> accept_prob = 0.30 (rejected!)
        [0.20, 0.50, 0.20, 0.10],  # pos 3: discarded after pos 2 rejection
        [0.25, 0.25, 0.25, 0.25],  # bonus pos 4
    ]
    uniform_draws = [0.42, 0.51, 0.74, 0.19]
    resample_draws = [0.30, 0.30, 0.45, 0.30, 0.30]

    step_result = verify_speculative_draft(
        draft_tokens=draft_tokens,
        draft_probs=draft_probs,
        target_probs=target_probs,
        uniform_draws=uniform_draws,
        resample_draws=resample_draws,
        use_residual=True,
    )

    p_pos2 = target_probs[2]
    q_pos2 = draft_probs[2]
    exact_marginal = marginal_output_distribution(p_pos2, q_pos2, use_residual=True)
    buggy_marginal = marginal_output_distribution(p_pos2, q_pos2, use_residual=False)

    return {
        "verification_step": step_result,
        "distribution_check_pos2": {
            "target_p": p_pos2,
            "draft_q": q_pos2,
            "residual_p_minus_q_norm": [
                round(x, 4) for x in residual_distribution(p_pos2, q_pos2)
            ],
            "tv_distance_with_residual": total_variation_distance(
                p_pos2, exact_marginal
            ),
            "tv_distance_without_residual": total_variation_distance(
                p_pos2, buggy_marginal
            ),
        },
        "batch_crossover": speculative_speedup_by_batch(gamma=4),
    }


def main() -> None:
    report = run_verification_demo()
    print(
        json.dumps(
            {
                "execution_mode": "CPU algorithm with controlled inputs; any latency/capacity coefficients are assumptions",
                **report,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
