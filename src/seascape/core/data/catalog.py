from __future__ import annotations
import pyarrow as pa
from .contracts import (
    DatasetFormat,
    DatasetId,
    DatasetLayer,
    DatasetSpec,
    ProcessingMode,
)
from .registry import DATASETS


def _register(
    dataset_id: str,
    layer: DatasetLayer,
    format: DatasetFormat,
    path: str,
    producer: str,
    *,
    dependencies: tuple[str, ...] = (),
    schema: pa.Schema | None = None,
    primary_key: tuple[str, ...] = (),
    partition_keys: tuple[str, ...] = (),
    modes: tuple[ProcessingMode, ...] | None = None,
    schema_version: str = "1",
) -> None:
    DATASETS.register(
        DatasetSpec(
            dataset_id=DatasetId(dataset_id),
            layer=layer,
            format=format,
            path_template=path,
            producer=producer,
            dependencies=tuple((DatasetId(item) for item in dependencies)),
            schema=schema,
            primary_key=primary_key,
            partition_keys=partition_keys,
            schema_version=schema_version,
            allowed_modes=modes or (ProcessingMode.RETROSPECTIVE, ProcessingMode.AS_OF),
        )
    )


def register_builtin_datasets():
    if tuple(DATASETS):
        return
    for resolution in (4, 5, 6, 7, 8):
        _register(
            f"environment.seascape.h3_geometry_r{resolution}",
            DatasetLayer.DOMAIN,
            DatasetFormat.PARQUET,
            f"{{data_root}}/processed/domain/environmental_layer/seascape/spatial_support/h3_geometry/H3_GRIDS_{resolution}.parquet",
            "environment.seascape.spatial_support.h3_geometry.build",
            dependencies=("environment.seascape.water_geometry",),
            primary_key=("H3_INDEX",),
            schema_version="1",
        )
        _register(
            f"environment.seascape.h3_geometry_clipped_r{resolution}",
            DatasetLayer.DOMAIN,
            DatasetFormat.PARQUET,
            f"{{data_root}}/processed/domain/environmental_layer/seascape/spatial_support/h3_geometry/H3_GRIDS_CLIPPED_{resolution}.parquet",
            "environment.seascape.spatial_support.h3_geometry.build",
            dependencies=(
                "environment.seascape.water_geometry",
                f"environment.seascape.h3_geometry_r{resolution}",
            ),
            primary_key=("H3_INDEX",),
            schema_version="1",
        )
    for resolution in (6, 8):
        support_dependency = f"environment.seascape.h3_geometry_clipped_r{resolution}"
        _register(
            f"environment.seascape.h3_full_marine_support_r{resolution}",
            DatasetLayer.DOMAIN,
            DatasetFormat.PARQUET,
            f"{{data_root}}/processed/domain/environmental_layer/seascape/spatial_support/h3_geometry/H3_MARINE_SUPPORT_RES_{resolution}.parquet",
            "environment.seascape.spatial_support.water_network.build",
            dependencies=("environment.seascape.water_geometry", support_dependency),
            primary_key=("H3_INDEX",),
            schema_version="1",
        )
        _register(
            f"environment.seascape.h3_marine_support_r{resolution}",
            DatasetLayer.DOMAIN,
            DatasetFormat.PARQUET,
            f"{{data_root}}/processed/domain/environmental_layer/seascape/spatial_support/h3_geometry/H3_MODEL_AREA_SUPPORT_RES_{resolution}.parquet",
            "environment.seascape.spatial_support.water_network.build",
            dependencies=(
                f"environment.seascape.h3_full_marine_support_r{resolution}",
            ),
            primary_key=("H3_INDEX",),
            schema_version="1",
        )
        _register(
            f"environment.seascape.h3_marine_full_geometry_r{resolution}",
            DatasetLayer.DOMAIN,
            DatasetFormat.PARQUET,
            f"{{data_root}}/processed/domain/environmental_layer/seascape/spatial_support/h3_geometry/H3_MARINE_FULL_CELL_GEOMETRY_RES_{resolution}.parquet",
            "environment.seascape.spatial_support.water_network.build",
            dependencies=(
                f"environment.seascape.h3_full_marine_support_r{resolution}",
            ),
            primary_key=("H3_INDEX",),
            schema_version="1",
        )
        _register(
            f"environment.seascape.h3_marine_clipped_geometry_r{resolution}",
            DatasetLayer.DOMAIN,
            DatasetFormat.PARQUET,
            f"{{data_root}}/processed/domain/environmental_layer/seascape/spatial_support/h3_geometry/H3_MARINE_WATER_CLIPPED_GEOMETRY_RES_{resolution}.parquet",
            "environment.seascape.spatial_support.water_network.build",
            dependencies=(
                f"environment.seascape.h3_full_marine_support_r{resolution}",
            ),
            primary_key=("H3_INDEX",),
            schema_version="1",
        )
        _register(
            f"environment.seascape.h3_water_edges_r{resolution}",
            DatasetLayer.DOMAIN,
            DatasetFormat.PARQUET,
            f"{{data_root}}/processed/domain/environmental_layer/seascape/spatial_support/water_network/H3_WATER_PASSABLE_EDGES_RES_{resolution}.parquet",
            "environment.seascape.spatial_support.water_network.build",
            dependencies=(
                f"environment.seascape.h3_full_marine_support_r{resolution}",
            ),
            primary_key=("SOURCE_H3_INDEX", "TARGET_H3_INDEX"),
            schema_version="1",
        )
        _register(
            f"environment.seascape.h3_water_connectors_r{resolution}",
            DatasetLayer.DOMAIN,
            DatasetFormat.PARQUET,
            f"{{data_root}}/processed/domain/environmental_layer/seascape/spatial_support/water_network/H3_WATER_CONNECTORS_RES_{resolution}.parquet",
            "environment.seascape.spatial_support.water_network.build",
            dependencies=(f"environment.seascape.h3_water_edges_r{resolution}",),
            primary_key=("H3_INDEX",),
            schema_version="1",
        )
        _register(
            f"environment.seascape.h3_water_neighborhoods_r{resolution}",
            DatasetLayer.DOMAIN,
            DatasetFormat.PARQUET,
            f"{{data_root}}/processed/domain/environmental_layer/seascape/spatial_support/water_network/H3_WATER_NEIGHBORHOODS_RES_{resolution}.parquet",
            "environment.seascape.spatial_support.water_network.build",
            dependencies=(
                f"environment.seascape.h3_water_edges_r{resolution}",
                f"environment.seascape.h3_water_connectors_r{resolution}",
                f"environment.seascape.h3_marine_support_r{resolution}",
            ),
            primary_key=("SOURCE_H3_INDEX", "TARGET_H3_INDEX"),
            schema_version="1",
        )
    _register(
        "environment.seascape.h3_parent_child_r8_to_r6",
        DatasetLayer.DOMAIN,
        DatasetFormat.PARQUET,
        "{data_root}/processed/domain/environmental_layer/seascape/spatial_support/h3_geometry/H3_PARENT_CHILD_RES_8_TO_RES_6.parquet",
        "environment.seascape.spatial_support.water_network.build",
        dependencies=(
            "environment.seascape.h3_marine_support_r6",
            "environment.seascape.h3_marine_support_r8",
        ),
        primary_key=("CHILD_H3_INDEX",),
        schema_version="1",
    )
    _register(
        "environment.seascape.h3_water_radius_operator_r8_5000m",
        DatasetLayer.DOMAIN,
        DatasetFormat.NPZ,
        "{data_root}/processed/domain/environmental_layer/seascape/spatial_support/water_network/H3_WATER_RADIUS_OPERATOR_RES_8_5000M.npz",
        "environment.seascape.spatial_support.water_network.build",
        dependencies=(
            "environment.seascape.h3_water_edges_r8",
            "environment.seascape.h3_water_connectors_r8",
            "environment.seascape.h3_marine_support_r8",
        ),
        schema_version="1",
    )
    _register(
        "environment.seascape.h3_reachable_water_area_r8_5000m",
        DatasetLayer.FEATURE,
        DatasetFormat.PARQUET,
        "{data_root}/processed/domain/environmental_layer/seascape/spatial_support/water_network/H3_REACHABLE_WATER_AREA_RES_8_5000M.parquet",
        "environment.seascape.spatial_support.water_network.build",
        dependencies=(
            "environment.seascape.h3_water_radius_operator_r8_5000m",
            "environment.seascape.h3_marine_support_r8",
        ),
        primary_key=("H3_INDEX",),
        schema_version="1",
    )
    for resolution, filename in ((6, "BATHYMETRY_RES_6"), (8, "BATHYMETRY")):
        _register(
            f"environment.seascape.bathymetry_r{resolution}",
            DatasetLayer.DOMAIN,
            DatasetFormat.PARQUET,
            f"{{data_root}}/processed/domain/environmental_layer/seascape/seafloor_physiography/bathymetry/{filename}.parquet",
            "environment.seascape.seafloor_physiography.bathymetry.build",
            dependencies=(
                f"environment.seascape.h3_marine_support_r{resolution}",
                f"environment.seascape.h3_water_neighborhoods_r{resolution}",
            ),
            primary_key=("H3_INDEX",),
            schema_version="1",
        )
    _register(
        "environment.seascape.geomorphometry_r8",
        DatasetLayer.DOMAIN,
        DatasetFormat.PARQUET,
        "{data_root}/processed/domain/environmental_layer/seascape/seafloor_physiography/geomorphometry/GEOMORPHOMETRY_RES_8.parquet",
        "environment.seascape.seafloor_physiography.geomorphometry.build",
        dependencies=("environment.seascape.bathymetry_r8",),
        primary_key=("H3_INDEX",),
        schema_version="1",
    )
    coastal_products = (
        (
            "shoreline_proximity",
            "shoreline_proximity/SHORELINE_PROXIMITY_RES_8.parquet",
            "environment.seascape.coastal_configuration.shoreline_proximity.build",
            (),
        ),
        (
            "exposure_and_enclosure",
            "exposure_and_enclosure/EXPOSURE_AND_ENCLOSURE_RES_8.parquet",
            "environment.seascape.coastal_configuration.exposure_and_enclosure.build",
            (),
        ),
        (
            "waterbody_morphometry",
            "waterbody_morphometry/WATERBODY_MORPHOMETRY_RES_8.parquet",
            "environment.seascape.coastal_configuration.waterbody_morphometry.build",
            ("environment.seascape.bathymetry_r8",),
        ),
    )
    for name, relative_path, producer, extra_dependencies in coastal_products:
        _register(
            f"environment.seascape.{name}_r8",
            DatasetLayer.DOMAIN,
            DatasetFormat.PARQUET,
            f"{{data_root}}/processed/domain/environmental_layer/seascape/coastal_configuration/{relative_path}",
            producer,
            dependencies=(
                "environment.seascape.h3_marine_support_r8",
                "environment.seascape.h3_water_edges_r8",
                *extra_dependencies,
            ),
            primary_key=("H3_INDEX",),
            schema_version="2",
        )
    for resolution in (6, 8):
        _register(
            f"environment.seascape.shoreline_characterization_r{resolution}",
            DatasetLayer.DOMAIN,
            DatasetFormat.PARQUET,
            f"{{data_root}}/processed/domain/environmental_layer/seascape/coastal_configuration/shoreline_characterization/SHORELINE_CHARACTERIZATION_RES_{resolution}.parquet",
            "environment.seascape.coastal_configuration.shoreline_characterization.build",
            dependencies=(
                f"environment.seascape.h3_marine_support_r{resolution}",
                f"environment.seascape.h3_water_edges_r{resolution}",
            ),
            primary_key=("H3_INDEX",),
            schema_version="1",
        )
    _register(
        "environment.seascape.geomorphic_units_r8",
        DatasetLayer.DOMAIN,
        DatasetFormat.PARQUET,
        "{data_root}/processed/domain/environmental_layer/seascape/seafloor_physiography/geomorphic_units/GEOMORPHIC_UNITS_RES_8.parquet",
        "environment.seascape.seafloor_physiography.geomorphic_units.build",
        dependencies=(
            "environment.seascape.bathymetry_r8",
            "environment.seascape.geomorphometry_r8",
            "environment.seascape.waterbody_morphometry_r8",
        ),
        primary_key=("H3_INDEX",),
        schema_version="1",
    )
    _register(
        "environment.seascape.freshwater_sources_r8",
        DatasetLayer.DOMAIN,
        DatasetFormat.PARQUET,
        "{data_root}/processed/domain/environmental_layer/seascape/hydrologic_connectivity/freshwater_sources/RIVER_MOUTH_FEATURES_RES_8.parquet",
        "environment.seascape.hydrologic_connectivity.freshwater_sources.build",
        dependencies=("environment.seascape.h3_marine_support_r8",),
        primary_key=("H3_INDEX",),
        schema_version="2",
    )
    _register(
        "environment.seascape.fluvial_connectivity_r8",
        DatasetLayer.DOMAIN,
        DatasetFormat.PARQUET,
        "{data_root}/processed/domain/environmental_layer/seascape/hydrologic_connectivity/fluvial_connectivity/FLUVIAL_CONNECTIVITY_RES_8.parquet",
        "environment.seascape.hydrologic_connectivity.fluvial_connectivity.build",
        dependencies=(
            "environment.seascape.h3_marine_support_r8",
            "environment.seascape.h3_water_edges_r8",
        ),
        primary_key=("H3_INDEX",),
        schema_version="2",
    )
    _register(
        "environment.seascape.estuarine_connectivity_r8",
        DatasetLayer.DOMAIN,
        DatasetFormat.PARQUET,
        "{data_root}/processed/domain/environmental_layer/seascape/hydrologic_connectivity/estuarine_connectivity/ESTUARINE_CONNECTIVITY_RES_8.parquet",
        "environment.seascape.hydrologic_connectivity.estuarine_connectivity.build",
        dependencies=(
            "environment.seascape.h3_marine_support_r8",
            "environment.seascape.h3_water_edges_r8",
        ),
        primary_key=("H3_INDEX",),
        schema_version="4",
    )
    for resolution in (6, 8):
        barrier_id = f"environment.seascape.fluvial_barriers_r{resolution}"
        _register(
            barrier_id,
            DatasetLayer.DOMAIN,
            DatasetFormat.PARQUET,
            f"{{data_root}}/processed/domain/environmental_layer/seascape/hydrologic_connectivity/fluvial_barriers/FLUVIAL_BARRIERS_RES_{resolution}.parquet",
            "environment.seascape.hydrologic_connectivity.fluvial_barriers.build",
            dependencies=(
                "environment.seascape.fluvial_connectivity_r8",
                f"environment.seascape.h3_marine_support_r{resolution}",
            ),
            primary_key=("H3_INDEX",),
            schema_version="1",
        )
        _register(
            f"environment.seascape.fluvial_barriers_confidence_r{resolution}",
            DatasetLayer.DOMAIN,
            DatasetFormat.PARQUET,
            f"{{data_root}}/processed/domain/environmental_layer/seascape/hydrologic_connectivity/fluvial_barriers/FLUVIAL_BARRIERS_CONFIDENCE_RES_{resolution}.parquet",
            "environment.seascape.hydrologic_connectivity.fluvial_barriers.build",
            dependencies=(barrier_id,),
            primary_key=("H3_INDEX",),
            schema_version="1",
        )
    habitat_products = (
        (
            "benthic_substrate_classification",
            "BENTHIC_SUBSTRATE_CLASSIFICATION",
            "benthic_substrate/classification",
            "environment.seascape.benthic_substrate.classification.build",
        ),
        (
            "bottom_hardness",
            "BOTTOM_HARDNESS",
            "benthic_substrate/bottom_hardness",
            "environment.seascape.benthic_substrate.bottom_hardness.build",
        ),
        (
            "seagrass_habitat",
            "SEAGRASS",
            "biogenic_habitat/seagrass",
            "environment.seascape.biogenic_habitat.seagrass.build",
        ),
        (
            "kelp_habitat",
            "KELP",
            "biogenic_habitat/kelp",
            "environment.seascape.biogenic_habitat.kelp.build",
        ),
        (
            "reef_habitat",
            "REEF_HABITAT",
            "biogenic_habitat/reef",
            "environment.seascape.biogenic_habitat.reef.build",
        ),
        (
            "benthic_habitat",
            "BENTHIC_HABITAT",
            "biogenic_habitat/composite",
            "environment.seascape.biogenic_habitat.composite.build",
        ),
    )
    for resolution in (6, 8):
        for name, filename, relative_directory, producer in habitat_products:
            dataset_id = f"environment.seascape.{name}_r{resolution}"
            native_graph_dependencies = (
                "environment.seascape.h3_marine_support_r8",
                "environment.seascape.h3_water_edges_r8",
            )
            aggregation_dependencies = (
                (
                    "environment.seascape.h3_marine_support_r6",
                    "environment.seascape.h3_parent_child_r8_to_r6",
                )
                if resolution == 6
                else ()
            )
            if name == "bottom_hardness":
                dependencies = (
                    f"environment.seascape.benthic_substrate_classification_r{resolution}",
                )
            elif name == "reef_habitat":
                dependencies = (
                    "environment.seascape.benthic_substrate_classification_r8",
                    "environment.seascape.bottom_hardness_r8",
                    "environment.seascape.bathymetry_r8",
                    "environment.seascape.geomorphometry_r8",
                    *native_graph_dependencies,
                    *aggregation_dependencies,
                )
            elif name == "benthic_habitat":
                dependencies = (
                    f"environment.seascape.seagrass_habitat_r{resolution}",
                    f"environment.seascape.kelp_habitat_r{resolution}",
                    f"environment.seascape.reef_habitat_r{resolution}",
                )
            elif name in {"seagrass_habitat", "kelp_habitat"}:
                dependencies = (*native_graph_dependencies, *aggregation_dependencies)
            else:
                dependencies = (
                    f"environment.seascape.h3_marine_support_r{resolution}",
                )
            _register(
                dataset_id,
                DatasetLayer.DOMAIN,
                DatasetFormat.PARQUET,
                f"{{data_root}}/processed/domain/environmental_layer/seascape/{relative_directory}/{filename}_RES_{resolution}.parquet",
                producer,
                dependencies=dependencies,
                primary_key=("H3_INDEX",),
                schema_version=(
                    "2"
                    if name
                    in {
                        "benthic_substrate_classification",
                        "bottom_hardness",
                        "reef_habitat",
                        "benthic_habitat",
                    }
                    else "1"
                ),
            )
            confidence_id = f"environment.seascape.{name}_confidence_r{resolution}"
            confidence_filename = (
                "BENTHIC_SUBSTRATE_CONFIDENCE"
                if name == "benthic_substrate_classification"
                else f"{filename}_CONFIDENCE"
            )
            _register(
                confidence_id,
                DatasetLayer.DOMAIN,
                DatasetFormat.PARQUET,
                f"{{data_root}}/processed/domain/environmental_layer/seascape/{relative_directory}/{confidence_filename}_RES_{resolution}.parquet",
                producer,
                dependencies=(dataset_id,),
                primary_key=("H3_INDEX",),
                schema_version=(
                    "2"
                    if name
                    in {
                        "benthic_substrate_classification",
                        "bottom_hardness",
                        "reef_habitat",
                        "benthic_habitat",
                    }
                    else "1"
                ),
            )
    for resolution in (6, 8):
        dataset_id = f"environment.seascape.anthropogenic_r{resolution}"
        dependencies = (
            "environment.seascape.h3_marine_support_r8",
            "environment.seascape.h3_water_edges_r8",
        )
        if resolution == 6:
            dependencies = (
                *dependencies,
                "environment.seascape.h3_marine_support_r6",
                "environment.seascape.h3_parent_child_r8_to_r6",
            )
        _register(
            dataset_id,
            DatasetLayer.DOMAIN,
            DatasetFormat.PARQUET,
            f"{{data_root}}/processed/domain/environmental_layer/seascape/anthropogenic/ANTHROPOGENIC_RES_{resolution}.parquet",
            "environment.seascape.anthropogenic.build",
            dependencies=dependencies,
            primary_key=("H3_INDEX",),
            schema_version="1",
        )
        _register(
            f"environment.seascape.anthropogenic_confidence_r{resolution}",
            DatasetLayer.DOMAIN,
            DatasetFormat.PARQUET,
            f"{{data_root}}/processed/domain/environmental_layer/seascape/anthropogenic/ANTHROPOGENIC_CONFIDENCE_RES_{resolution}.parquet",
            "environment.seascape.anthropogenic.build",
            dependencies=(dataset_id,),
            primary_key=("H3_INDEX",),
            schema_version="1",
        )
    definitions = (
        (
            "environment.seascape.water_geometry",
            "{data_root}/processed/domain/environmental_layer/seascape/spatial_support/water_geometry/TERRITORIAL_WATER_POLYGON.parquet",
        ),
    )

    for resolution in (4, 5, 6):
        _register(
            f"environment.seascape.h3_full_counting_universe_r{resolution}",
            DatasetLayer.DOMAIN,
            DatasetFormat.PARQUET,
            f"{{data_root}}/processed/environment/seascape/full_counting/H3_WATER_UNIVERSE_{resolution}.parquet",
            "environment.seascape.spatial_support.h3_geometry.build",
            dependencies=("environment.seascape.water_geometry",),
            primary_key=("H3_INDEX",),
            schema_version="1",
        )

    for dataset_id, path in definitions:
        _register(
            dataset_id, DatasetLayer.DOMAIN, DatasetFormat.PARQUET, path, dataset_id
        )
