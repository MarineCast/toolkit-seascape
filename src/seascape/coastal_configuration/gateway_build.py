"""Optional reviewed gateway attachments and derived-graph route diagnostics."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import geopandas as gpd
import pandas as pd
from pyproj import Transformer
from shapely.geometry import Point

from seascape.core.config.data import load_data_config
from seascape.core.config.paths import project_root
from seascape.core.geo.h3 import cell_to_parent
from seascape.spatial_support.water_network.load import (
    load_model_area_support,
    load_water_graph,
)
from seascape.utils.artifacts import (
    build_manifest,
    checksum_artifact,
    stage_parquet_family,
)

from .gateways import (
    alternate_route_after_gateway_removal,
    basin_membership,
    corridor_coordinates,
    gateway_relationships,
)


@dataclass(frozen=True)
class GatewayConfig:
    registry_path: Path
    attachments_path: Path
    routes_path: Path | None
    basins_path: Path | None
    corridors_path: Path | None
    output_dir: Path
    projected_crs: str
    resolutions: tuple[int, ...]
    max_cells: int
    max_pairs: int
    max_distance_m: float | None
    attachment_tolerance_m: float
    corridor_max_offset_m: float
    selected_h3_indices: tuple[str, ...]


def load_gateway_config(config_path: str | Path) -> GatewayConfig:
    raw = load_data_config(config_path, domains="SEASCAPE_LAYER")
    section = raw.get("geographic_gateways")
    if (
        not isinstance(section, dict)
        or not section.get("registry_path")
        or not section.get("attachments_path")
    ):
        raise ValueError(
            "Set geographic_gateways registry_path and water-valid attachments_path"
        )
    root = project_root()

    def optional_path(key: str) -> Path | None:
        return root / str(section[key]) if section.get(key) else None

    output = root / str(
        section.get(
            "output_dir",
            "data/processed/domain/environmental_layer/seascape/coastal_configuration/geographic_gateways",
        )
    )
    if not output.resolve().is_relative_to(root.resolve()):
        raise ValueError("Gateway output escapes workspace")
    resolutions = tuple(int(value) for value in section.get("resolutions", (8, 6)))
    if (
        not resolutions
        or len(set(resolutions)) != len(resolutions)
        or not set(resolutions) <= {6, 8}
    ):
        raise ValueError("Gateway resolutions must be unique R8 and/or R6")
    max_cells = int(section.get("max_cells", 200))
    max_pairs = int(section.get("max_pairs", 200_000))
    tolerance = float(section.get("attachment_tolerance_m", 1000))
    corridor_offset = float(section.get("corridor_max_offset_m", 1000))
    if min(max_cells, max_pairs, tolerance, corridor_offset) <= 0:
        raise ValueError("Gateway bounds and tolerances must be positive")
    max_distance = section.get("max_distance_m")
    return GatewayConfig(
        root / str(section["registry_path"]),
        root / str(section["attachments_path"]),
        optional_path("routes_path"),
        optional_path("basins_path"),
        optional_path("corridors_path"),
        output,
        str(section.get("projected_crs", "EPSG:32610")),
        resolutions,
        max_cells,
        max_pairs,
        float(max_distance) if max_distance is not None else None,
        tolerance,
        corridor_offset,
        tuple(str(value) for value in section.get("selected_h3_indices", ())),
    )


def build_geographic_gateways(config_path: str | Path) -> tuple[Path, ...]:
    config = load_gateway_config(config_path)
    gateways = gpd.read_parquet(config.registry_path)
    required = {"GATEWAY_ID", "SOURCE_ID", "SOURCE_VERSION", "RIGHTS"}
    if gateways.crs is None or required - set(gateways):
        raise ValueError(
            f"Gateway registry requires CRS and fields {sorted(required - set(gateways))}"
        )
    if (
        gateways.GATEWAY_ID.isna().any()
        or gateways.GATEWAY_ID.duplicated().any()
        or gateways.empty
    ):
        raise ValueError("Gateway IDs must be unique and nonempty")
    if not gateways.geometry.is_valid.all() or gateways.geometry.is_empty.any():
        raise ValueError("Gateway geometry must be valid and nonempty")
    gateways = gateways.to_crs(config.projected_crs).sort_values("GATEWAY_ID")
    attachment = pd.read_parquet(config.attachments_path)
    required_attachment = {
        "GATEWAY_ID",
        "H3_RESOLUTION",
        "GRAPH_H3_INDEX",
        "GATEWAY_CONNECTOR_DISTANCE_M",
        "WATER_PATH_VALID",
    }
    if (
        required_attachment - set(attachment)
        or attachment.duplicated(
            ["GATEWAY_ID", "H3_RESOLUTION", "GRAPH_H3_INDEX"]
        ).any()
    ):
        raise ValueError(
            "Gateway attachments lack required fields or have duplicate identity"
        )
    if not attachment.WATER_PATH_VALID.eq(True).all() or set(
        attachment.GATEWAY_ID
    ) - set(gateways.GATEWAY_ID):
        raise ValueError(
            "Gateway attachment must be reviewed water-valid and reference known geometry"
        )
    basin_geometry = {}
    if config.basins_path:
        basins = gpd.read_parquet(config.basins_path).to_crs(config.projected_crs)
        if (
            "BASIN_ID" not in basins
            or basins.BASIN_ID.isna().any()
            or basins.BASIN_ID.duplicated().any()
        ):
            raise ValueError("Basin IDs must be unique")
        basin_geometry = dict(
            zip(basins.BASIN_ID.astype(str), basins.geometry, strict=True)
        )
    corridor_geometry = {}
    if config.corridors_path:
        corridors = gpd.read_parquet(config.corridors_path).to_crs(config.projected_crs)
        if (
            "CORRIDOR_ID" not in corridors
            or corridors.CORRIDOR_ID.isna().any()
            or corridors.CORRIDOR_ID.duplicated().any()
        ):
            raise ValueError("Corridor IDs must be unique")
        corridor_geometry = dict(
            zip(corridors.CORRIDOR_ID.astype(str), corridors.geometry, strict=True)
        )
    frames = []
    route_rows = []
    for resolution in config.resolutions:
        graph = load_water_graph(resolution, config_path)
        support = load_model_area_support(resolution, config_path)
        if config.selected_h3_indices:
            selected = (
                set(config.selected_h3_indices)
                if resolution == 8
                else {cell_to_parent(cell, 6) for cell in config.selected_h3_indices}
            )
            missing = selected - set(support.H3_INDEX.astype(str))
            if missing:
                raise KeyError(
                    f"Selected gateway cells absent from R{resolution}: {sorted(missing)}"
                )
            support = support.loc[support.H3_INDEX.isin(selected)]
        if support.empty or len(support) > config.max_cells:
            raise ValueError(
                f"Gateway R{resolution} cell count exceeds bound {config.max_cells}"
            )
        local = attachment.loc[attachment.H3_RESOLUTION.eq(resolution)]
        if set(gateways.GATEWAY_ID) - set(local.GATEWAY_ID):
            raise ValueError(
                f"Every gateway needs at least one R{resolution} attachment"
            )
        transformer = Transformer.from_crs(
            "EPSG:4326", config.projected_crs, always_xy=True
        )
        graph_support = graph.support.set_index("H3_INDEX")
        for row in local.itertuples(index=False):
            if str(row.GRAPH_H3_INDEX) not in graph.cell_to_position:
                raise ValueError("Gateway attachment outside canonical graph")
            node = graph_support.loc[str(row.GRAPH_H3_INDEX)]
            x, y = transformer.transform(
                node.REPRESENTATIVE_POINT_LONGITUDE, node.REPRESENTATIVE_POINT_LATITUDE
            )
            gateway_geometry = (
                gateways.set_index("GATEWAY_ID").loc[str(row.GATEWAY_ID)].geometry
            )
            if Point(x, y).distance(
                gateway_geometry
            ) > config.attachment_tolerance_m + float(row.GATEWAY_CONNECTOR_DISTANCE_M):
                raise ValueError(
                    "Gateway attachment is inconsistent with reviewed geometry"
                )
        local_cells = pd.DataFrame(
            {
                "H3_INDEX": support.H3_INDEX.astype(str),
                "H3_RESOLUTION": resolution,
                "GRAPH_H3_INDEX": support.H3_INDEX.astype(str),
                "TARGET_CONNECTOR_DISTANCE_M": support.CONNECTOR_DISTANCE_M.fillna(
                    0
                ).to_numpy(),
            }
        )
        # Terminal mappings are supplied by canonical support; never add them as edges.
        from seascape.spatial_support.water_network.graph import target_graph_mapping

        positions, connectors, _qc = target_graph_mapping(
            graph, local_cells.H3_INDEX.tolist()
        )
        if (positions < 0).any():
            raise ValueError(
                "Selected gateway support includes unmapped terminal cells"
            )
        local_cells["GRAPH_H3_INDEX"] = [
            str(graph.cells[int(position)]) for position in positions
        ]
        local_cells["TARGET_CONNECTOR_DISTANCE_M"] = connectors
        result = gateway_relationships(
            local_cells,
            local,
            graph,
            max_pairs=config.max_pairs,
            max_distance_m=config.max_distance_m,
        )
        x_values, y_values = transformer.transform(
            support.REPRESENTATIVE_POINT_LONGITUDE.to_numpy(),
            support.REPRESENTATIVE_POINT_LATITUDE.to_numpy(),
        )
        points = {
            cell: Point(x, y)
            for cell, x, y in zip(
                support.H3_INDEX.astype(str), x_values, y_values, strict=True
            )
        }
        membership = {
            cell: basin_membership(point, basin_geometry)
            for cell, point in points.items()
        }
        result["BASIN_ID"] = result.H3_INDEX.map(lambda cell: membership[cell][0])
        result["BASIN_MEMBERSHIP_STATUS"] = result.H3_INDEX.map(
            lambda cell: membership[cell][1]
        )
        if corridor_geometry:
            if len(corridor_geometry) != 1:
                result["CORRIDOR_STATUS"] = "ambiguous_multiple_corridors"
            else:
                corridor_id, axis = next(iter(corridor_geometry.items()))
                coords = {
                    cell: corridor_coordinates(
                        point, axis, max_lateral_offset_m=config.corridor_max_offset_m
                    )
                    for cell, point in points.items()
                }
                result["CORRIDOR_ID"] = corridor_id
                result["ALONG_AXIS_POSITION_M"] = result.H3_INDEX.map(
                    lambda cell: coords[cell][0]
                )
                result["LATERAL_OFFSET_M"] = result.H3_INDEX.map(
                    lambda cell: coords[cell][1]
                )
                result["CORRIDOR_STATUS"] = result.H3_INDEX.map(
                    lambda cell: coords[cell][2]
                )
        frames.append(
            (
                result,
                config.output_dir / f"GATEWAY_RELATIONSHIPS_RES_{resolution}.parquet",
            )
        )
        if config.routes_path:
            routes = pd.read_parquet(config.routes_path)
            required_routes = {
                "ROUTE_ID",
                "H3_RESOLUTION",
                "GATEWAY_ID",
                "SOURCE_GRAPH_H3_INDEX",
                "TARGET_GRAPH_H3_INDEX",
                "GATEWAY_EDGE_SET_JSON",
            }
            if (
                required_routes - set(routes)
                or routes.ROUTE_ID.isna().any()
                or routes.duplicated(["ROUTE_ID", "H3_RESOLUTION"]).any()
            ):
                raise ValueError(
                    "Gateway routes have missing fields or duplicate identity"
                )
            for route in routes.loc[routes.H3_RESOLUTION.eq(resolution)].itertuples(
                index=False
            ):
                if route.GATEWAY_ID not in set(gateways.GATEWAY_ID):
                    raise ValueError("Route references unknown gateway")
                edges = json.loads(route.GATEWAY_EDGE_SET_JSON)
                diagnostic = alternate_route_after_gateway_removal(
                    graph,
                    str(route.SOURCE_GRAPH_H3_INDEX),
                    str(route.TARGET_GRAPH_H3_INDEX),
                    [(str(a), str(b)) for a, b in edges],
                    max_search_m=config.max_distance_m,
                )
                route_rows.append(
                    {
                        "ROUTE_ID": route.ROUTE_ID,
                        "H3_RESOLUTION": resolution,
                        "GATEWAY_ID": route.GATEWAY_ID,
                        **diagnostic,
                    }
                )
    routes_output = pd.DataFrame(
        route_rows,
        columns=[
            "ROUTE_ID",
            "H3_RESOLUTION",
            "GATEWAY_ID",
            "PRIMARY_ROUTE_LENGTH_M",
            "ALTERNATE_ROUTE_LENGTH_AFTER_GATEWAY_REMOVAL_M",
            "ALTERNATE_ROUTE_STATUS",
        ],
    )
    outputs = [
        (gateways, config.output_dir / "GATEWAY_INVENTORY.parquet"),
        (attachment, config.output_dir / "GATEWAY_ATTACHMENTS.parquet"),
        *frames,
        (routes_output, config.output_dir / "GATEWAY_ROUTE_DIAGNOSTICS.parquet"),
    ]
    publisher = stage_parquet_family(config.output_dir, outputs)
    source_paths = [
        config.registry_path,
        config.attachments_path,
        *(
            path
            for path in (config.routes_path, config.basins_path, config.corridors_path)
            if path
        ),
    ]
    manifest = build_manifest(
        dataset_family="environment.seascape.geographic_gateways",
        run_id=publisher.run_id,
        resolved_config=asdict(config),
        artifacts=publisher.artifacts,
        project_root=project_root(),
        sources=[
            {
                "name": path.name,
                "path": str(path),
                "checksum": checksum_artifact(path),
                "license": "Per-registry RIGHTS field",
            }
            for path in source_paths
        ],
        upstream_artifacts=[],
        attribution=[],
        source_completeness="partial",
        metadata={
            "scientific_method_version": "reviewed_gateway_graph_distance_v1",
            "sample_support": "canonical water graph, water-valid reviewed gateway attachments, representative-point R8/R6 targets",
        },
    )
    publisher.publish_manifest(
        config.output_dir / "geographic_gateways_manifest.json", manifest
    )
    return tuple(path for _frame, path in outputs)
