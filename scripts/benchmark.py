"""
Performance benchmark script: stage timings for 100,000 records and vectorised vs row-loop comparison.
"""

from pathlib import Path
import shutil
import sys
import time
import pandas as pd

# Add src to pythonpath
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from recon.config import PipelineConfig, ReconConfig
from recon.generator import generate_dataset
from recon.ingest import ingest_csv
from recon.publish import publish_all
from recon.reconcile import _compare_fields_vectorised, run_reconciliation
from recon.schemas import (
    CUSTOMERS_ALL_COLUMNS,
    CUSTOMERS_REQUIRED_COLUMNS,
    ORDERS_ALL_COLUMNS,
    ORDERS_REQUIRED_COLUMNS,
    RECON_EXCLUDE_COLUMNS,
)
from recon.transform import transform_customers, transform_orders
from recon.validate import validate_customers, validate_orders


def naive_field_compare(exp_df: pd.DataFrame, act_df: pd.DataFrame, pk_col: str, tol: float = 0.005):
    """Naive row-by-row iteration for field comparison (used as optimization baseline)."""
    act_dict = {row[pk_col]: row for _, row in act_df.iterrows()}
    mismatches = []
    compare_cols = [c for c in exp_df.columns if c not in RECON_EXCLUDE_COLUMNS and c != pk_col]

    for _, exp_row in exp_df.iterrows():
        pk = exp_row[pk_col]
        if pk in act_dict:
            act_row = act_dict[pk]
            for col in compare_cols:
                if col in act_row:
                    v_src = str(exp_row[col]).strip()
                    v_tgt = str(act_row[col]).strip()
                    if col == "amount":
                        try:
                            if abs(float(v_src) - float(v_tgt)) > tol:
                                mismatches.append((pk, col, v_src, v_tgt))
                        except ValueError:
                            mismatches.append((pk, col, v_src, v_tgt))
                    else:
                        if v_src != v_tgt:
                            mismatches.append((pk, col, v_src, v_tgt))
    return mismatches


def run_benchmark(records: int = 100000):
    print("=" * 70)
    print(f"STARTING RECONCILIATION BENCHMARK ({records:,} ORDERS)")
    print("=" * 70)

    bench_dir = Path("tmp_bench")
    shutil.rmtree(bench_dir, ignore_errors=True)
    bench_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Stage 0: Generation
        t0 = time.perf_counter()
        print(f"Generating synthetic data ({records:,} orders, 10,000 customers)...")
        generate_dataset(
            out_dir=bench_dir,
            num_customers=10000,
            num_orders=records,
            seed=42,
            inject_defects=False,
        )
        t_gen = time.perf_counter() - t0
        print(f"  -> Generated in {t_gen:.2f} s")

        cust_file = bench_dir / "source" / "customers.csv"
        orders_file = bench_dir / "source" / "orders.csv"
        target_dir = bench_dir / "target"
        out_dir = bench_dir / "out"

        cfg = PipelineConfig(
            source_dir=bench_dir / "source",
            target_dir=target_dir,
            out_dir=out_dir,
        )

        # Stage 1: Ingest
        t0 = time.perf_counter()
        raw_c, rej_c = ingest_csv(cust_file, "customers", CUSTOMERS_REQUIRED_COLUMNS, CUSTOMERS_ALL_COLUMNS, "b1")
        raw_o, rej_o = ingest_csv(orders_file, "orders", ORDERS_REQUIRED_COLUMNS, ORDERS_ALL_COLUMNS, "b1")
        t_ingest = time.perf_counter() - t0
        print(f"1. Ingestion:           {t_ingest:.3f} s  ({len(raw_o):,} orders read)")

        # Stage 2: Validation
        t0 = time.perf_counter()
        val_c, _ = validate_customers(raw_c, "b1", cust_file.name, cfg)
        c_ids = set(val_c["customer_id"].astype(str))
        val_o, _ = validate_orders(raw_o, c_ids, "b1", orders_file.name, cfg)
        t_val = time.perf_counter() - t0
        print(f"2. Validation & Dedup:  {t_val:.3f} s  ({len(val_o):,} valid orders)")

        # Stage 3: Transform
        t0 = time.perf_counter()
        tgt_c = transform_customers(val_c, "b1", cust_file.name)
        tgt_o = transform_orders(val_o, "b1", orders_file.name)
        t_trans = time.perf_counter() - t0
        print(f"3. Transformation:      {t_trans:.3f} s  (rounded money & derived bands)")

        # Stage 4: Publish
        t0 = time.perf_counter()
        pub_metrics = publish_all(tgt_c, tgt_o, target_dir)
        t_pub = time.perf_counter() - t0
        print(f"4. Idempotent Publish:  {t_pub:.3f} s  (atomic CSV replace)")

        # Stage 5: Full 4-Tier Reconciliation (with vectorised merge comparison)
        r_cfg = ReconConfig(source_dir=bench_dir / "source", target_dir=target_dir, out_dir=out_dir)
        t0 = time.perf_counter()
        res = run_reconciliation(bench_dir / "source", target_dir, "b1", r_cfg)
        t_recon = time.perf_counter() - t0
        print(f"5. Reconciliation:      {t_recon:.3f} s  (PASS: {res.passed})")

        # Optimization Experiment: Vectorised Compare vs Naive iterrows Loop
        print("\n" + "-" * 70)
        print("OPTIMIZATION STUDY: Vectorised Merge vs Naive Row Loop")
        print("-" * 70)
        sub_n = min(15000, len(tgt_o))
        sample_exp = tgt_o.head(sub_n)
        sample_act = pd.read_csv(target_dir / "fact_orders.csv", dtype=str).head(sub_n)

        # Naive timing
        t0 = time.perf_counter()
        naive_field_compare(sample_exp, sample_act, "order_id")
        t_naive = time.perf_counter() - t0

        # Vectorised timing
        t0 = time.perf_counter()
        _compare_fields_vectorised("orders", "order_id", sample_exp, sample_act, 0.005)
        t_vec = time.perf_counter() - t0

        speedup = t_naive / t_vec if t_vec > 0 else 1.0
        print(f"Sample size: {sub_n:,} rows")
        print(f"  - Naive iterrows loop:     {t_naive:.3f} s")
        print(f"  - Vectorised pandas merge: {t_vec:.3f} s")
        print(f"  - Measured Speedup:        {speedup:.1f}x faster")
        print("-" * 70)

        # Write evidence file
        evidence_dir = Path("docs/evidence")
        evidence_dir.mkdir(parents=True, exist_ok=True)
        evidence_file = evidence_dir / "benchmark.txt"
        with open(evidence_file, "w", encoding="utf-8") as f:
            f.write(f"RECONCILIATION ENGINE BENCHMARK EVIDENCE\n")
            f.write(f"Orders volume: {records:,}\n")
            f.write(f"Ingestion:          {t_ingest:.3f} s\n")
            f.write(f"Validation & Dedup: {t_val:.3f} s\n")
            f.write(f"Transformation:     {t_trans:.3f} s\n")
            f.write(f"Publish:            {t_pub:.3f} s\n")
            f.write(f"Reconciliation:     {t_recon:.3f} s\n")
            f.write(f"Total end-to-end:   {(t_ingest+t_val+t_trans+t_pub+t_recon):.3f} s\n\n")
            f.write(f"OPTIMIZATION STUDY ({sub_n:,} rows sample):\n")
            f.write(f"Naive iterrows loop:     {t_naive:.3f} s\n")
            f.write(f"Vectorised merge diff:   {t_vec:.3f} s\n")
            f.write(f"Speedup:                 {speedup:.1f}x\n")

        print(f"\nEvidence written to {evidence_file}")

    finally:
        shutil.rmtree(bench_dir, ignore_errors=True)


if __name__ == "__main__":
    records = 100000
    if len(sys.argv) > 1:
        records = int(sys.argv[1])
    run_benchmark(records)
