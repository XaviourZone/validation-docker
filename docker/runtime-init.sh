#!/bin/sh
set -eu

mkdir -p \
  runtime/data_inflow/SAIS_IOR \
  runtime/data_inflow/SAIS_GLOBAL \
  runtime/data_inflow/MSIS \
  runtime/data_inflow/LRIT \
  runtime/spool/pending \
  runtime/spool/delivered \
  runtime/spool/failed \
  runtime/router-state \
  runtime/router-logs \
  runtime/parser-logs \
  runtime/parser-state \
  runtime/forwarder-state \
  runtime/reference

printf '%s\n' "Runtime directories initialized."
