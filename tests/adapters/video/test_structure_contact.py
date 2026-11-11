"""The footprint, the entry-or-end pairing and the three-of-three load drop.
No clip and no network: python -m unittest discover -s tests"""

import unittest

import numpy as np

from faultline.adapters.video import measure

SITE = {"consequence_window_s": 0.5}  # 6 frames at 12 fps


class Footprint(unittest.TestCase):
    def test_footprint_carries_hidden_side_to_site_size(self):
        env = np.array([[0.0, 0.0], [0.5, 0.0], [1.0, 0.0]])
        poly = measure.footprint(env, np.array([1.0, 0.0]), np.array([0.0, 1.0]), 3.0, 1.15)
        self.assertTrue(np.isclose(poly[:, 0].min(), 0.0) and np.isclose(poly[:, 0].max(), 3.0))
        self.assertTrue(np.isclose(poly[:, 1].min(), 0.0) and np.isclose(poly[:, 1].max(), 1.15))

    def test_poly_seg_dist_zero_on_cross_and_positive_apart(self):
        sq = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
        self.assertEqual(
            measure.poly_seg_dist(sq, np.array([0.5, -1.0]), np.array([0.5, 2.0])), 0.0
        )
        self.assertTrue(
            np.isclose(measure.poly_seg_dist(sq, np.array([1.3, -1.0]), np.array([1.3, 2.0])), 0.3)
        )


class Pairing(unittest.TestCase):
    def test_onset_after_the_run_end_pairs(self):
        d = {"truck": True, "strip_runs": [["rack", 31, 38]]}
        self.assertTrue(measure.contact_pairs(d, [[44, "load drop"]], SITE))  # 38 + 6 frames
        self.assertFalse(measure.contact_pairs(d, [[45, "load drop"]], SITE))
        self.assertTrue(
            measure.contact_pairs(d, [[25, "zone-surround change"]], SITE)
        )  # 31 - 6: the entry, read either side
        self.assertFalse(measure.contact_pairs(d, [[24, "zone-surround change"]], SITE))

    def test_onset_at_the_strip_entry_pairs(self):
        d = {"truck": True, "strip_runs": [["rack", 12, 49]]}
        p = measure.contact_pairs(
            d, [[12, "zone-surround change"], [18, "zone-surround change"]], SITE
        )
        self.assertEqual([x["event"] for x in p], [12, 18])
        self.assertEqual({x["at"] for x in p}, {"entry"})

    def test_onset_inside_a_long_run_never_pairs(self):
        # the reader's case: a run from frame 13 to 59 and a change at 27, 31 and 47 inside it
        d = {"truck": True, "strip_runs": [["upright", 13, 59]]}
        self.assertFalse(
            measure.contact_pairs(
                d,
                [
                    [27, "zone-surround change"],
                    [31, "zone-surround change"],
                    [47, "zone-surround change"],
                ],
                SITE,
            )
        )
        self.assertTrue(measure.contact_pairs(d, [[53, "zone-surround change"]], SITE))  # 59 - 6
        self.assertTrue(measure.contact_pairs(d, [[62, "zone-surround change"]], SITE))

    def test_truck_stop_at_a_dock_face_is_not_a_consequence(self):
        d = {"truck": True, "strip_runs": [["trailer_rear", 55, 60]]}
        self.assertFalse(measure.contact_pairs(d, [[59, "truck stop"]], SITE, ["trailer_rear"]))
        self.assertTrue(
            measure.contact_pairs(d, [[59, "zone-surround change"]], SITE, ["trailer_rear"])
        )
        self.assertTrue(measure.contact_pairs(d, [[59, "truck stop"]], SITE, []))


class LoadDrop(unittest.TestCase):
    def _box(self, y: int) -> np.ndarray:
        m = np.zeros((measure.H, measure.W), dtype=bool)
        m[y : y + 30, 100:130] = True
        return m

    def test_a_fall_is_read_and_a_truck_overlap_is_not(self):
        load = {"1": {f: self._box(100 + 12 * f) for f in range(6)}}
        self.assertEqual(measure.load_drops(load, {}, 20)[0][0], 0)
        truck = {
            f: self._box(100 + 12 * f) for f in range(6)
        }  # the truck covers the box on every frame
        self.assertEqual(measure.load_drops(load, truck, 20), [])

    def test_drop_needs_all_three_reads(self):
        a, b, c = [[43, "1", 90.0]], [[44, "2", 52.0]], [[42, "1", 74.0]]
        self.assertEqual(measure.agreed_drops([a, b, c]), [[42, "load drop"]])
        self.assertEqual(measure.agreed_drops([a, b, []]), [])  # two of three is not enough
        self.assertEqual(
            measure.agreed_drops([a, b, [[20, "1", 60.0]]]), []
        )  # the third read sees it elsewhere


if __name__ == "__main__":
    unittest.main()
