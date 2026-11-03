"""
Command Line Interface for generator, pipeline execution, and reconciliation verification.
"""

import argparse
import logging
from pathlib import Path
import sys

from recon import PIPELINE_VERSION
from recon.config import PipelineConfig, ReconConfig
from recon.generator import generate_dataset
from recon.ingest import ingest_csv
from recon.publish import publish_all
from recon.reconcile import run_reconciliation
from recon.report import write_reconciliation_artifacts
from recon.runlog import RunContext, compute_run_id, setup_logger
from recon.schemas import (
    CUSTOMERS_ALL_COLUMNS,
    CUSTOMERS_REQUIRED_COLUMNS,
    ORDERS_ALL_COLUMNS,
    ORDERS_REQUIRED_COLUMNS,
    REJECT_COLUMNS,
)
from recon.transform import transform_customers, transform_orders
from recon.validate import validate_customers, validate_orders
import pandas as pd


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="recon",
        description="YottaFlex Data Pipeline & Source-to-Target Reconciliation Tool",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {PIPELINE_VERSION}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Generate command
    gen_parser = subparsers.add_parser("generate", help="Generate synthetic test datasets with injected defects")
    gen_parser.add_argument("--out", type=Path, default=Path("data/sample"), help="Target output directory")
    gen_parser.add_argument("--customers", type=int, default=50, help="Number of customer entities")
    gen_parser.add_argument("--orders", type=int, default=200, help="Number of order entities")
    gen_parser.add_argument("--seed", type=int, default=42, help="Deterministic random seed")

    # Run command
    run_parser = subparsers.add_parser("run", help="Execute the ingestion, validation, and publish pipeline")
    run_parser.add_argument("--source-dir", type=Path, required=True, help="Input directory containing source CSVs")
    run_parser.add_argument("--target-dir", type=Path, required=True, help="Target publishing directory")
    run_parser.add_argument("--out-dir", type=Path, required=True, help="Artifacts/manifest output directory")
    run_parser.add_argument("--amount-tolerance", type=float, default=0.005, help="Numeric tolerance for comparison")
    run_parser.add_argument("--log-level", type=str, default="INFO", help="Logging level")

    # Reconcile command
    rec_parser = subparsers.add_parser("reconcile", help="Execute 4-tier reconciliation against target datasets")
    rec_parser.add_argument("--source-dir", type=Path, required=True, help="Input directory containing source CSVs")
    rec_parser.add_argument("--target-dir", type=Path, required=True, help="Target directory containing published CSVs")
    rec_parser.add_argument("--out-dir", type=Path, required=True, help="Reconciliation report output directory")
    rec_parser.add_argument("--amount-tolerance", type=float, default=0.005, help="Numeric tolerance for comparison")
    rec_parser.add_argument("--log-level", type=str, default="INFO", help="Logging level")

    return parser


def handle_generate(args) -> int:
    paths = generate_dataset(
        out_dir=args.out,
        num_customers=args.customers,
        num_orders=args.orders,
        seed=args.seed,
    )
    print(f"Generated datasets at {args.out}:")
    for k, v in paths.items():
        print(f"  - {k}: {v}")
    return 0


def handle_run(args) -> int:
    source_dir: Path = args.source_dir
    target_dir: Path = args.target_dir
    out_dir: Path = args.out_dir

    cust_file = source_dir / "customers.csv"
    orders_file = source_dir / "orders.csv"
    run_id = compute_run_id([cust_file, orders_file])

    logger = setup_logger(run_id, log_level=args.log_level, log_file=out_dir / "pipeline.log")

    with RunContext(command="run", run_id=run_id, out_dir=out_dir) as ctx:
        logger.info("Starting pipeline execution for run %s", run_id)
        config = PipelineConfig(
            source_dir=source_dir,
            target_dir=target_dir,
            out_dir=out_dir,
            amount_tolerance=args.amount_tolerance,
        )

        # 1. Ingestion
        logger.info("Ingesting source files from %s", source_dir)
        raw_cust_df, ingest_cust_rejects = ingest_csv(
            file_path=cust_file,
            entity="customers",
            required_columns=CUSTOMERS_REQUIRED_COLUMNS,
            all_known_columns=CUSTOMERS_ALL_COLUMNS,
            run_id=run_id,
        )
        raw_orders_df, ingest_orders_rejects = ingest_csv(
            file_path=orders_file,
            entity="orders",
            required_columns=ORDERS_REQUIRED_COLUMNS,
            all_known_columns=ORDERS_ALL_COLUMNS,
            run_id=run_id,
        )

        # 2. Validation & Deduplication
        logger.info("Validating entities and checking referential integrity")
        valid_cust_df, val_cust_rejects = validate_customers(
            raw_cust_df, run_id=run_id, source_file=cust_file.name, config=config
        )
        all_cust_rejects = pd.concat([ingest_cust_rejects, val_cust_rejects], ignore_index=True)

        valid_cust_ids = set(valid_cust_df["customer_id"].astype(str)) if not valid_cust_df.empty else set()
        valid_orders_df, val_orders_rejects = validate_orders(
            raw_orders_df,
            valid_customer_ids=valid_cust_ids,
            run_id=run_id,
            source_file=orders_file.name,
            config=config,
        )
        all_orders_rejects = pd.concat([ingest_orders_rejects, val_orders_rejects], ignore_index=True)

        # 3. Deterministic Transformation
        logger.info("Applying business transforms and normalisation")
        dim_customers = transform_customers(valid_cust_df, run_id=run_id, source_file=cust_file.name)
        fact_orders = transform_orders(valid_orders_df, run_id=run_id, source_file=orders_file.name)

        # 4. Idempotent Publishing
        logger.info("Publishing datasets to %s", target_dir)
        pub_metrics = publish_all(dim_customers, fact_orders, target_dir)

        # 5. Persist quarantined rejects
        rejects_dir = out_dir / "rejects"
        rejects_dir.mkdir(parents=True, exist_ok=True)
        all_cust_rejects.to_csv(rejects_dir / "customers_rejects.csv", index=False)
        all_orders_rejects.to_csv(rejects_dir / "orders_rejects.csv", index=False)

        # Update telemetry
        ctx.input_counts = {
            "customers_raw": len(raw_cust_df) + len(ingest_cust_rejects),
            "orders_raw": len(raw_orders_df) + len(ingest_orders_rejects),
        }
        ctx.output_counts = {
            "customers_published": len(dim_customers),
            "orders_published": len(fact_orders),
        }
        ctx.rejected_count = len(all_cust_rejects) + len(all_orders_rejects)

        logger.info("Pipeline completed successfully. Metrics: %s", pub_metrics)
        print(f"Run {run_id} completed successfully. Target published to {target_dir}")
        print(f"Metrics: {pub_metrics}")
        return 0


def handle_reconcile(args) -> int:
    source_dir: Path = args.source_dir
    target_dir: Path = args.target_dir
    out_dir: Path = args.out_dir

    cust_file = source_dir / "customers.csv"
    orders_file = source_dir / "orders.csv"
    run_id = compute_run_id([cust_file, orders_file])

    logger = setup_logger(run_id, log_level=args.log_level, log_file=out_dir / "reconcile.log")

    with RunContext(command="reconcile", run_id=run_id, out_dir=out_dir) as ctx:
        logger.info("Executing reconciliation between %s and %s", source_dir, target_dir)
        config = ReconConfig(
            source_dir=source_dir,
            target_dir=target_dir,
            out_dir=out_dir,
            amount_tolerance=args.amount_tolerance,
        )

        result = run_reconciliation(source_dir, target_dir, run_id, config)
        exit_code = write_reconciliation_artifacts(result, out_dir)

        ctx.input_counts = {
            "customers_expected": result.entities["customers"].expected_target_count,
            "orders_expected": result.entities["orders"].expected_target_count,
        }
        ctx.output_counts = {
            "customers_actual": result.entities["customers"].actual_target_count,
            "orders_actual": result.entities["orders"].actual_target_count,
        }
        ctx.rejected_count = (
            result.entities["customers"].rejected_count + result.entities["orders"].rejected_count
        )

        if exit_code == 0:
            ctx.status = "SUCCESS"
            print("========================================")
            print("RECONCILIATION RESULT: PASS")
            print("========================================")
            print("0 unexplained differences found. All keys, counts, and aggregates reconciled.")
        else:
            ctx.status = "FAILED"
            ctx.failure_reason = "RECON_MISMATCHES_DETECTED"
            print("========================================")
            print("RECONCILIATION RESULT: FAIL (Mismatches Detected)")
            print("========================================")
            print(f"Total mismatched records: {result.total_mismatches}")
            print(f"Isolated mismatch reports written to {out_dir / 'mismatches'}")

        print(f"Full report written to {out_dir / 'reconciliation_report.json'}")
        return exit_code


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "generate":
            return handle_generate(args)
        elif args.command == "run":
            return handle_run(args)
        elif args.command == "reconcile":
            return handle_reconcile(args)
        else:
            parser.print_help()
            return 1
    except Exception as e:
        print(f"FATAL ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
