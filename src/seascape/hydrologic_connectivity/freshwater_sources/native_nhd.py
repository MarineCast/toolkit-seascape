"""Legacy NHD archive adaptation with explicit network-end evidence and unknowns."""

from __future__ import annotations

import json

import geopandas as gpd
import pandas as pd


def normalize_legacy_nhd(flowlines, flow):
    """Return unique unambiguous source features, quarantined conflicts and QA.

    NHDFlow direction 713 with receiving ID 0 identifies a network end. A 709
    record ending at 0 can be an extraction boundary and never establishes a
    terminal. Conflicting downstream records remain unknown. These are static
    archive network attributes, not a historical discharge or mouth census.
    """
    line_fields = {
        "permanent_identifier",
        "ftype",
        "fcode",
        "gnis_name",
        "geometry",
        "SOURCE_HU4",
        "SOURCE_ROW_ID",
    }
    flow_fields = {"direction", "from_permanent_identifier", "to_permanent_identifier"}
    if line_fields - set(flowlines) or flow_fields - set(flow) or flowlines.crs is None:
        raise ValueError(
            "Native NHD features and flow table require source IDs, fields and CRS"
        )
    if flowlines[list(line_fields - {"geometry", "gnis_name"})].isna().any().any():
        raise ValueError("Native NHD identity and feature codes must be nonnull")
    if flowlines.SOURCE_ROW_ID.duplicated().any():
        raise ValueError("Duplicate native NHD source occurrence identity")

    def keys(values):
        return values.astype("string").str.strip().str.strip("{}").str.lower()

    origin, receiving = (
        keys(flow.from_permanent_identifier),
        keys(flow.to_permanent_identifier),
    )
    direction = pd.to_numeric(flow.direction, errors="raise")
    terminal = set(origin.loc[direction.eq(713) & receiving.eq("0")].dropna()) - {"0"}
    downstream = set(origin.loc[direction.eq(709) & receiving.ne("0")].dropna()) - {"0"}
    conflict = terminal & downstream
    lines = flowlines.copy()
    lines["COMID"] = keys(lines.permanent_identifier)
    if lines.COMID.isna().any() or lines.COMID.isin(["", "0"]).any():
        raise ValueError("Invalid native NHD permanent identifier")
    duplicates = lines.loc[lines.COMID.duplicated(keep=False)]
    bad_ids = set()
    for identifier, rows in duplicates.groupby("COMID", sort=True):
        signatures = {
            (
                row.geometry.wkb,
                int(row.ftype),
                int(row.fcode),
                None if pd.isna(row.gnis_name) else str(row.gnis_name),
            )
            for row in rows.itertuples(index=False)
        }
        if len(signatures) != 1:
            bad_ids.add(identifier)
    quarantine = lines.loc[lines.COMID.isin(bad_ids)].copy()
    eligible = lines.loc[~lines.COMID.isin(bad_ids)].sort_values(
        ["COMID", "SOURCE_ROW_ID"]
    )
    members = eligible.groupby("COMID").SOURCE_ROW_ID.agg(
        lambda rows: json.dumps(sorted(rows.astype(str)))
    )
    # All semantic/geometry duplicates were explicitly compared above. This
    # deterministic representative preserves their complete source-member list.
    eligible = eligible.drop_duplicates("COMID").copy()
    eligible["SOURCE_MEMBER_IDS_JSON"] = eligible.COMID.map(members)
    eligible["TERMINALFL"] = pd.Series(pd.NA, index=eligible.index, dtype="Int64")
    eligible.loc[eligible.COMID.isin(downstream - terminal), "TERMINALFL"] = 0
    eligible.loc[eligible.COMID.isin(terminal - downstream), "TERMINALFL"] = 1
    eligible["TERMINAL_QC"] = "unknown_no_qualifying_flow_record"
    eligible.loc[eligible.TERMINALFL.eq(0).fillna(False), "TERMINAL_QC"] = (
        "documented_downstream_flow"
    )
    eligible.loc[eligible.TERMINALFL.eq(1).fillna(False), "TERMINAL_QC"] = (
        "documented_network_end_713_to_zero"
    )
    eligible.loc[eligible.COMID.isin(conflict), "TERMINAL_QC"] = (
        "conflicting_network_end_and_downstream_flow"
    )
    eligible["SOURCE_DATASET"] = "US_NHD_HR_LEGACY"
    eligible = eligible.rename(
        columns={
            "ftype": "FTYPE",
            "fcode": "FCODE",
            "gnis_name": "GNIS_NAME",
            "permanent_identifier": "PERMANENT_IDENTIFIER",
        }
    )
    keep = [
        "COMID",
        "PERMANENT_IDENTIFIER",
        "FTYPE",
        "FCODE",
        "GNIS_NAME",
        "TERMINALFL",
        "TERMINAL_QC",
        "SOURCE_DATASET",
        "SOURCE_MEMBER_IDS_JSON",
        "geometry",
    ]
    output = gpd.GeoDataFrame(
        eligible[keep], geometry="geometry", crs=flowlines.crs
    ).reset_index(drop=True)
    report = {
        "method": "legacy_NHD_flow_network_end_713_v1",
        "raw_feature_occurrences": len(lines),
        "unique_unambiguous_features": len(output),
        "quarantined_occurrences": len(quarantine),
        "conflicting_feature_ids": sorted(bad_ids),
        "terminal_qc_counts": output.TERMINAL_QC.value_counts().to_dict(),
        "source_temporal_support": "static legacy archive snapshot; not annual observations",
        "source_completeness": "partial",
        "vertical_coordinates_qualified": False,
    }
    return output, quarantine, report
