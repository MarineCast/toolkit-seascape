import unittest

from shapely.geometry import Point, box

from seascape.regional.bivalve import IndexedEvidence


class Checks(unittest.TestCase):
    def test_duplicate_union(self):
        v = IndexedEvidence([(box(0, 0, 2, 2), "BC_mussel")] * 2).calculate(
            box(-1, -1, 3, 3), Point(1, 1)
        )
        self.assertEqual(
            (v["union_area"], v["record_sum"], v["overlap_excess"], v["distance"]),
            (4, 8, 4, 0),
        )

    def test_partial_class_overlap(self):
        v = IndexedEvidence(
            [(box(0, 0, 2, 2), "WA_bed"), (box(1, 0, 3, 2), "BC_observation")]
        ).calculate(box(-1, -1, 4, 4), Point(4, 1))
        self.assertEqual(
            (v["union_area"], v["WA_BC_overlap"], v["distance"]), (6, 2, 1)
        )

    def test_no_intersection_distance(self):
        v = IndexedEvidence([(box(0, 0, 1, 1), "WA_bed")]).calculate(
            box(2, 2, 3, 3), Point(2, 1)
        )
        self.assertEqual(
            (v["union_area"], v["candidate_records"], v["distance"]), (0, 0, 1)
        )

    def test_boundary_contact(self):
        v = IndexedEvidence([(box(0, 0, 1, 1), "WA_bed")]).calculate(
            box(1, 0, 2, 1), Point(1, 0.5)
        )
        self.assertEqual((v["union_area"], v["distance"]), (0, 0))

    def test_distinct_equally_near(self):
        v = IndexedEvidence(
            [(box(-2, 0, -1, 1), "WA_bed"), (box(1, 0, 2, 1), "BC_observation")]
        ).calculate(box(-3, -1, 3, 2), Point(0, 0.5))
        self.assertEqual(v["distance"], 1)


if __name__ == "__main__":
    unittest.main()
