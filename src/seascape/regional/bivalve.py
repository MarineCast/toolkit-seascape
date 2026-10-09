"""Exact per-record intersection unions and nearest polygon distance using STRtree."""

import shapely


class IndexedEvidence:
    def __init__(self, records):
        self.geometries = [g for g, c in records]
        self.classes = [c for g, c in records]
        self.tree = shapely.STRtree(self.geometries)
        self.categories = sorted(set(self.classes))

    def calculate(self, cell, centre):
        indices = self.tree.query(cell, predicate="intersects")
        pieces = [
            (self.geometries[int(i)].intersection(cell), self.classes[int(i)])
            for i in indices
        ]
        unions = {
            c: shapely.union_all([g for g, k in pieces if k == c])
            for c in self.categories
        }
        overall = shapely.union_all([g for g, c in pieces])
        rawsum = sum(g.area for g, c in pieces)
        nearest = int(self.tree.nearest(centre))
        distance = centre.distance(self.geometries[nearest])
        wa = shapely.union_all([g for g, c in pieces if c.startswith("WA_")])
        bc = shapely.union_all([g for g, c in pieces if c.startswith("BC_")])
        return {
            "union_area": overall.area,
            "record_sum": rawsum,
            "overlap_excess": max(0, rawsum - overall.area),
            "WA_BC_overlap": wa.intersection(bc).area,
            "distance": distance,
            "class_areas": {c: g.area for c, g in unions.items()},
            "candidate_records": len(indices),
        }
