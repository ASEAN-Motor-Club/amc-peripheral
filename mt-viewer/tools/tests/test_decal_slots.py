import unittest

from tools.mk_manifest import decal_slots


def cdo(name, **props):
    return {"ExportName": f"Default__{name}_C", "Properties": props}


class DecalSlotsTest(unittest.TestCase):
    def test_unions_body_and_decalable_names(self):
        exports = [cdo("Kuda_LiveFishTank_4x2",
                       BodyMaterialNames=["Body_01", "Body_02"],
                       DecalableMaterialSlotNames=["Palette_Decal", "CargoBed"])]
        self.assertEqual(
            decal_slots(exports, "Kuda_LiveFishTank_4x2")["decalSlots"],
            ["Body_01", "Body_02", "Palette_Decal", "CargoBed"],
        )

    def test_body_names_alone_still_count(self):
        exports = [cdo("Vista", BodyMaterialNames=["Body_01"])]
        self.assertEqual(decal_slots(exports, "Vista")["decalSlots"], ["Body_01"])

    def test_base_blueprint_supplies_missing_list(self):
        exports = [cdo("Zydro_Police")]
        base = [cdo("Zydro",
                    BodyMaterialNames=["Body_01"],
                    DecalableMaterialSlotNames=["Body_02"])]
        self.assertEqual(
            decal_slots(exports, "Zydro_Police", base, "Zydro")["decalSlots"],
            ["Body_01", "Body_02"],
        )

    def test_empty_vehicle_gets_no_guessed_slots(self):
        self.assertEqual(decal_slots([cdo("Nothing")], "Nothing")["decalSlots"], [])


if __name__ == "__main__":
    unittest.main()
