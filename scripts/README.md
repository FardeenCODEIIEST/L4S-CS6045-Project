# scripts/

This folder contains the helper scripts used to run the fixed baseline experiments, run the dynamic controller ablation sweep, summarize results, compute confidence intervals, and generate plots.

Run commands from the project root.

Several experiment commands require `sudo` because they start Mininet/BMv2 topology processes.

## Main Workflow

The current experiment workflow has two parts:

1. Run fixed-threshold baseline experiments manually.
2. Run dynamic-controller ablation experiments with `scripts/run_ablation.py`.
3. Summarize result folders into `summary.json`.
4. Generate fixed-baseline confidence intervals.
5. Generate ablation confidence intervals and plots.

## Fixed Baseline Runs

The fixed baseline runs are done manually with `topo/topology.py --run-fixed`.

Use this helper variable:

```bash
export RUN="sudo env PATH=$PATH PYTHONPATH=."
```

Run three fixed trials:

```bash
$RUN python3 topo/topology.py \
  --run-fixed \
  --experiment-duration 180 \
  --l4s-bw 10.0 \
  --classic-bw 10.0 \
  --output-dir results/fixed_run_1

$RUN python3 topo/topology.py \
  --run-fixed \
  --experiment-duration 180 \
  --l4s-bw 10.0 \
  --classic-bw 10.0 \
  --output-dir results/fixed_run_2

$RUN python3 topo/topology.py \
  --run-fixed \
  --experiment-duration 180 \
  --l4s-bw 10.0 \
  --classic-bw 10.0 \
  --output-dir results/fixed_run_3
```

After each run, or after all three runs complete, summarize them:

```bash
python3 -m eval.summarize_results results/fixed_run_1
python3 -m eval.summarize_results results/fixed_run_2
python3 -m eval.summarize_results results/fixed_run_3
```

This creates `summary.json` files under each `results/fixed_run_*` directory.

## Dynamic Ablation Runs

Dynamic ablation runs are automated by `scripts/run_ablation.py`.

The script sweeps:

- `relax_step` in `{1, 2, 4, 8, 16, 32}`
- `tighten_step` in `{1, 2, 4, 8, 16, 32}`
- trials `1, 2, 3`

That is `6 x 6 x 3 = 108` dynamic runs. Each run currently uses:

- experiment duration: `180` seconds
- L4S bandwidth: `10.0` Mbps
- Classic bandwidth: `10.0` Mbps
- base config: `topo/config_fair_dynamic.yaml`

Run the full dynamic sweep:

```bash
$RUN python3 scripts/run_ablation.py run
```

Output directories are named:

```text
results/dynamic_run_{trial}_relax_{relax_step}_tighten_{tighten_step}/
```

For example:

```text
results/dynamic_run_1_relax_4_tighten_8/
```

`run_ablation.py run` also calls `eval.summarize_results` after each successful dynamic run. This thing might show errors, but those can be ignored as summarisation is skipped

If summaries need to be regenerated manually, use:

```bash
for dir in results/dynamic_run_*_relax_*_tighten_*/; do
  python3 -m eval.summarize_results "$dir"
done
```

## Dynamic CI Analysis

After the dynamic runs have completed and each result directory has a `summary.json`, compute confidence intervals:

```bash
sudo python3 scripts/run_ablation.py analyze
```

This reads the dynamic result summaries and writes:

```text
results/ablation_plots/confidence_intervals.json
```

The CI metrics include:

- `l4s_mbps`
- `classic_mbps`
- `jain_fairness`
- `l4s_share`

## Fixed Baseline CI

After the fixed runs have been summarized, generate the fixed baseline confidence interval JSON:

```bash
sudo python3 scripts/generate_fixed_baseline_ci.py
```

By default this reads:

```text
results/fixed_run_*
```

and writes:

```text
results/ablation_plots/fixed_baseline_ci.json
```

You can override the input pattern or output path:

```bash
sudo python3 scripts/generate_fixed_baseline_ci.py \
  --pattern "results/fixed_run_*" \
  --output results/ablation_plots/fixed_baseline_ci.json
```

## Plot Generation

Generate heatmaps and CI error-bar plots:

```bash
sudo python3 scripts/plot_ablation.py
```

Inputs:

```text
results/ablation_plots/confidence_intervals.json
results/ablation_plots/fixed_baseline_ci.json
```

Outputs:

```text
results/ablation_plots/heatmap_l4s_mbps.pdf
results/ablation_plots/heatmap_classic_mbps.pdf
results/ablation_plots/heatmap_jain_fairness.pdf
results/ablation_plots/ci_errorbar_l4s_mbps_relax_<RelaxStep>.pdf
results/ablation_plots/ci_errorbar_classic_mbps_relax_<RelaxStep>.pdf
results/ablation_plots/ci_errorbar_jain_fairness_relax_<RelaxStep>.pdf
```

Each CI error-bar plot is one figure for one `RelaxStep`. The blue curve shows the dynamic mean with 95% CI error bars. The black horizontal lines show the fixed baseline mean and fixed baseline 95% CI when `fixed_baseline_ci.json` is present.

Use a custom output directory if needed:

```bash
sudo python3 scripts/plot_ablation.py --output-dir results/my_plots
```

## End-to-End Command Order

A typical full workflow is:

```bash
# 1. Run fixed baseline trials manually.
export RUN="sudo env PATH=$PATH PYTHONPATH=." 
$RUN python3 topo/topology.py --run-fixed --experiment-duration 180 --l4s-bw 10.0 --classic-bw 10.0 --output-dir results/fixed_run_1
$RUN python3 topo/topology.py --run-fixed --experiment-duration 180 --l4s-bw 10.0 --classic-bw 10.0 --output-dir results/fixed_run_2
$RUN python3 topo/topology.py --run-fixed --experiment-duration 180 --l4s-bw 10.0 --classic-bw 10.0 --output-dir results/fixed_run_3

# 2. Summarize fixed baseline trials.
python3 -m eval.summarize_results results/fixed_run_1
python3 -m eval.summarize_results results/fixed_run_2
python3 -m eval.summarize_results results/fixed_run_3

# 3. Run dynamic ablation sweep.
$RUN python3 scripts/run_ablation.py run

# 4. Generate the summary.jsons for the dynamic runs
for dir in results/dynamic_run_*/; do
    python3 -m eval.summarize_results "$dir"
done

# 5. Compute dynamic confidence intervals.
sudo python3 scripts/run_ablation.py analyze

# 6. Compute fixed baseline confidence intervals.
sudo python3 scripts/generate_fixed_baseline_ci.py

# 7. Generate plots.
sudo python3 scripts/plot_ablation.py
```



## Notes

- If `results/ablation_plots` or result directories were created with `sudo`, later plot or JSON writes may also require `sudo`.
- `scripts/run_ablation.py run` can take several hours because it runs 108 trials, you can tune the duration in the script as per your convenience
- `scripts/run_ablation.py analyze`, `scripts/generate_fixed_baseline_ci.py`, and `scripts/plot_ablation.py` operate on existing result files and do not start Mininet, but still require sudo.
