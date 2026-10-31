"""The operator rule and the rear cone, on hand-made tracks."""

import unittest

from faultline.adapters.video import operator


def truck(n=20, x0=500, dx=0):
    return {
        "boxes": {f: (x0 + dx * f, 200, x0 + 200 + dx * f, 500) for f in range(n)},
        "masks": None,
    }


class OperatorRule(unittest.TestCase):
    def test_seated_driver_riding_the_truck_is_dropped(self):
        t = truck(dx=5)
        person = {
            f: (560 + 5 * f, 220, 620 + 5 * f, 380) for f in range(20)
        }  # feet 120 px above the truck's floor line
        self.assertTrue(operator.classify(person, [t])["operator"])

    def test_walker_crossing_in_front_is_kept(self):
        t = truck()
        person = {
            f: (450 + 15 * f, 300, 510 + 15 * f, 560) for f in range(20)
        }  # feet below the truck: on the floor in front
        self.assertFalse(operator.classify(person, [t])["operator"])

    def test_walker_behind_the_truck_who_does_not_ride_is_kept(self):
        t = truck()
        person = {
            f: (420 + 12 * f, 150, 470 + 12 * f, 400) for f in range(20)
        }  # legs hidden, but walking across
        self.assertFalse(operator.classify(person, [t])["operator"])

    def test_driver_of_a_second_truck_is_dropped(self):
        a, b = truck(), truck(x0=900, dx=-4)
        person = {f: (960 - 4 * f, 220, 1020 - 4 * f, 380) for f in range(20)}
        r = operator.classify(person, [a, b])
        self.assertTrue(r["operator"])
        self.assertEqual(r["truck"], 1)

    def test_short_shared_track_is_never_dropped(self):
        t = truck(n=4)
        person = {f: (560, 220, 620, 380) for f in range(4)}
        self.assertFalse(operator.classify(person, [t])["operator"])


if __name__ == "__main__":
    unittest.main()
