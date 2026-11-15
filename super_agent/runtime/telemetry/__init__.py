"""Run correlation for telemetry records.

The record contract and its process-wide routing live in
``runtime/protocol/telemetry.py``; this package only attaches the run and action
identity to a run context.
"""

from super_agent.runtime.telemetry.telemetry import (
    IDs as IDs,
    i_ds_from as i_ds_from,
    with_i_ds as with_i_ds,
)
