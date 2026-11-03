# Physical shoreline characterization

The product combines two authoritative, jurisdiction-specific shoreline inventories:

- Washington State marine shoreline geomorphic classes from the 2018 NOAA/NWFSC
  Puget Sound shoreline typology. Attribution: NOAA Northwest Fisheries Science
  Center; United States Government work.
- British Columbia ShoreZone shore-unit classifications. Attribution: Province of
  British Columbia; Open Government Licence - British Columbia.

Raw labels, source segment identifiers, jurisdiction, and observation date are
retained in `SHORELINE_SEGMENTS.parquet`. A class is asserted only when the source
label explicitly supports it. `Modified`, `Man-made`, `Undefined`, and unmapped
segments do not enter the physical-class denominator; armoring remains a separate
anthropogenic feature.

Fractions use physically classified shoreline length as the denominator. Classes
may overlap (for example, a rocky cliff), so their fractions are not compositional
and may sum above one. Coverage is published separately. Straight distances use the
configured projected CRS; ecological distances use the canonical water graph and
retain null values plus QC reasons when disconnected.

Physical lengths use cell-local geometric unions, independent of source-record
multiplicity. Total mapped length is the union of all retained line evidence;
classified length is the union where at least one source record has an accepted
physical classification. Each class numerator is its own accepted-evidence union.
No snapping or first-record selection is used. Raw source records and IDs remain
unchanged. The legacy `SHORELINE_CLASSIFIED_COVERAGE_FRAC` describes classification
share of unique mapped shoreline, not independent survey coverage.

Optional evidence diagnostics measure overlap between classified and unclassified
records and overlap between differing accepted class-membership sets. These
disagreements do not discard accepted evidence or impose exclusive classes;
multiple class labels remain possible. An unclassified placeholder coincident with
classified evidence does not erase that classification. Regions with no accepted
classification retain null class fractions.

## Collection

Run `python -m seascape.coastal_configuration.shoreline_characterization.download --config config/data/environment_seascape.yaml`
to collect the NOAA archive and BC WFS snapshot. The archive URL is listed by the
[NOAA SHSTMP data page](https://www.fisheries.noaa.gov/resource/map/salmon-habitat-status-and-trend-monitoring-program-data).
The command stages acquisition separately, validates source components and installs
them at the existing consumed paths. `--validate-only` performs the offline check;
`--overwrite` explicitly refreshes differing snapshots. Source/query identity,
retrieval time and checksums are retained in the acquisition manifest.
