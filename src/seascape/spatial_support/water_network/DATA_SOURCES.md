# Canonical H3 marine support and water network

The sole water-domain input is the canonical
`spatial_support/water_geometry/TERRITORIAL_WATER_POLYGON.parquet` product. Its
source attribution and licensing flow into the water-network manifest. The
manifest records the source checksum, resolved topology thresholds, output
checksums, and the explicit `territorial_water_v1` and
`marine_spatial_support_v1` versions.

H3 r6 and r8 support is overlap-based and retains every positively wet cell.
Full-cell and exact water-clipped geometries are separate one-to-one products.
Cell and water areas use WGS84 ellipsoidal geodesic area; land area is the
validated complement. `INTERSECTS_SHORELINE` means intersection with the
operational canonical water-mask boundary, while `IS_AOI_BOUNDARY_CELL` is
calculated independently from the configured full-area boundary.

The graph includes only true H3 one-ring candidates whose endpoint cells meet
the configured direct-node threshold. A densified geodesic segment connects
deterministic interior representative points. The segment is passable only when
no more than one metre of geodesic path lies outside the canonical water mask.
Rejected neighbor candidates remain in the edge table for scientific QC.

Edges are stored once as undirected `(SOURCE_H3_INDEX, TARGET_H3_INDEX)` rows in
lexical order. Components use the smallest member H3 index as their stable ID.
Bounded, water-valid connectors attach otherwise unresolved cells as terminal
outputs only and never merge components or become graph intermediates.

The r8-to-r6 crosswalk always uses the H3 library's `cell_to_parent` identity.
H3 hierarchy is not a geometric subdivision: an r8 hexagon can intersect water
even when its indexed r6 parent's hexagon does not. Such rows retain the exact
parent index with `PARENT_IN_MARINE_SUPPORT=false`, zero parent water area and
fraction, and null parent component lineage.
