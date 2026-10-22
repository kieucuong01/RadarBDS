#!/usr/bin/env python3
"""Daily engine for immutable MTD asking-price packets; no publishing/social/DB writes.

Run from the deployed source after crawl. The operator owns live URL and Google
receipts; this script computes facts deterministically without an LLM.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from services.data_price_seo import (
    TZ, CONTRACT, SCOPES, canonical_bytes, digest, build_snapshot,
    read_current_rows, select_cohort, freeze_snapshot, snapshot_root, validate_snapshot,
)


def source_commit():
    return subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True,timeout=10).strip()


def refresh(root):
    root=Path(root)
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (root/'.refresh.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        now=datetime.now(TZ)
        as_of=now.date()
        rows=read_current_rows(os.environ['DATABASE_URL'],as_of)
        # The source query verifies READ ONLY on its own transaction.
        prior=[]
        for path in sorted(root.glob('20*.json')):
            old=validate_snapshot(json.loads(path.read_text()))
            if old['contract_version']==CONTRACT and old['data_as_of']<as_of.isoformat():
                prior.append(old)
        snapshot=build_snapshot(rows,as_of=as_of,generated_at=now.isoformat(),
                                source_commit=source_commit(),previous=prior)
        cohort={slug:select_cohort(rows,slug,as_of) for slug in SCOPES}
        valid={r['id']:r for group in cohort.values() for r in group}
        fields = ('id', 'source', 'ward', 'property_type', 'tx_type', 'price_ty',
                  'price_per_m2', 'area_m2', 'last_seen_at', 'is_active',
                  'duplicate_of_id', 'possibly_duplicate', 'is_blacklisted',
                  'review_hidden', 'is_outlier', 'suspicious_bait', 'probably_sold',
                  'source_status', 'extraction_quality_flags', 'source_quality_flags',
                  'valuation_is_outlier')
        records = [{key: valid[k].get(key) for key in fields} for k in sorted(valid)]
        private=dict(snapshot_id=snapshot['snapshot_id'],snapshot_sha256=snapshot['sha256'],
                     source_commit=snapshot['source_commit'],read_only=True,
                     generated_at=now.isoformat(),data_as_of=as_of.isoformat(),
                     scope_listing_ids={slug:[r['id'] for r in values] for slug,values in cohort.items()},
                     cohort_records=records,cohort_input_sha256=digest(records),
                     queried_record_count=len(rows),query_contract=CONTRACT)
        private_root=root/'private'
        private_root.mkdir(exist_ok=True,mode=0o700)
        private_path=private_root/(snapshot['snapshot_id']+'.json')
        content=canonical_bytes(private)+b'\n'
        try:
            with private_path.open('xb') as f:
                os.chmod(private_path,0o600)
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
        except FileExistsError:
            if private_path.read_bytes()!=content:
                raise ValueError('private provenance collision')
        path=freeze_snapshot(snapshot,root)
        return dict(status='FROZEN',read_only=True,path=str(path),
                    snapshot_id=snapshot['snapshot_id'],snapshot_sha256=snapshot['sha256'],
                    period_start=snapshot['period_start'],period_end=snapshot['period_end'],
                    source_commit=snapshot['source_commit'],
                    scopes={slug:dict(sample_count=s['sample_count'],active_count=s['active_count'],
                                     source_counts=s['source_counts'],eligible=s['eligible'])
                            for slug,s in snapshot['scopes'].items()})


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=snapshot_root())
    args=parser.parse_args(argv)
    try:
        result=refresh(args.output_dir)
    except Exception as exc:
        # Do not print connection strings or SQL parameters from driver errors.
        print(json.dumps(dict(status='UNKNOWN',error_type=type(exc).__name__)),file=sys.stderr)
        return 1
    print(json.dumps(result,ensure_ascii=False))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
