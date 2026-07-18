#!/usr/bin/env sh
set -u

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR" || exit 2

metricproof experiments validate || exit $?
metricproof scan --show-claims || exit $?
metricproof link --non-interactive --json || exit $?

metricproof check
check_status=$?
if [ "$check_status" -ne 1 ]; then
  echo "Expected metricproof check to exit 1; got $check_status" >&2
  [ "$check_status" -eq 0 ] && exit 2
  exit "$check_status"
fi

metricproof report \
  --format html \
  --output metricproof-report.html \
  --no-timestamp
report_status=$?
if [ "$report_status" -ne 1 ]; then
  echo "Expected metricproof report to exit 1; got $report_status" >&2
  [ "$report_status" -eq 0 ] && exit 2
  exit "$report_status"
fi

echo "Created $SCRIPT_DIR/metricproof-report.html"
echo "Demo findings intentionally meet the configured threshold."
exit 1
