# Training and checkpoints

Evolution evaluates a population on common random seeds, retains elites, uses
uniform parameter crossover (identical architectures only), and Gaussian masked
mutation. Hybrid refines leading candidates with PPO and accepts them on fresh
seeds. PPO trains independent population members with persistent Adam state and
no genetic selection. All methods use the selected plugin. Champion selection
uses a fixed validation split; validation is not a withheld test result.

PPO uses complete on-policy trajectories, clipped log-probability ratios, entropy
regularization, critic MSE, normalized GAE and gradient clipping. Terminations
bootstrap zero; truncations bootstrap the critic's final observation. Rewards are
used by PPO; plugin fitness is used by evolutionary selection. Built-in game
rewards/fitness are unchanged. CPU is the supported execution default.

All environment interactions (population evaluation, validation, PPO, acceptance)
are counted. `environment_step_budget` stops at a completed generation boundary,
so it can overshoot by a generation. Compare histories at an explicit matched
step budget rather than equal generation counts. Timing is measured wall time;
fitness standard deviation/spread are score statistics, not genetic diversity.
The baseline evaluator supplies random policies and built-in Snake/Flappy
heuristics; label independently chosen seeds as withheld test data.

## Configuration

`Config`: game, mode (evolution/ppo/hybrid), population, generations, elites,
ppo_candidates, ppo_episodes, eval_episodes, size, max_steps, seed,
mutation_probability, mutation_sigma, hidden (integer -> two equal layers, or a
list of widths), game_config (plugin keyword dict), environment_step_budget.
`size` configures built-ins; external games receive only game_config.
Only the generations target may change when resuming. Game/plugin version and
architecture must match. Set eval episodes and population to fit CPU budgets.

## Checkpoint schema 1

New `.pt` files wrap a restricted PyTorch tensor archive in an EVOFORGE-1 header
and SHA256 digest. Writes fsync a temporary file, replace atomically and fsync the
directory. A valid previous primary is preserved as `.bak`. No unrestricted
pickle loading is used. SHA256 detects accidental corruption, not an adversary
who can rewrite the file; use only trusted artifacts and installed plugins.

A checkpoint is a generation commit: population, optimizer states, champion,
champion history, architecture, config, RNGs, counters, lineage, and metric
history. CSV, champion and spectator files are derived after commit. Recovery
reconciles CSV by generation and republishes artifacts. If interrupted in a
generation, work since the last commit repeats; committed metrics do not repeat.
A corrupt primary falls back to the valid backup. Pre-recovery CSV is backed up.
Large histories/lineage currently remain in checkpoints (scaling limitation).

v0.9 tensor/primitive-only archives are read through `weights_only=True` without
requiring conversion. Legacy metrics keep their original columns. Missing legacy
optimizer/step history cannot be reconstructed; counters begin at zero after
migration. Unsafe or incompatible files are rejected with diagnostics. Never
replace historical run folders during installation.

Use `evoforge migrate PATH` for dry-run, `evoforge migrate PATH --apply` to wrap an
archive with integrity protection. Apply creates `.v090-original` and `.bak`.
This converts storage only; architecture/config validation still occurs on resume.
