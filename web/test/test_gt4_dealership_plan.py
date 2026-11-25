import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location("dealership",Path(__file__).resolve().parents[1]/"tools"/"gt4-dealership-plan.py")
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def source():
    rows=[]
    for i in range(58):
        rows.append({"id":f"STOCK{i}" if i<46 else mod.ADDONS[i-46],
                     "index":i,"hash":f"{i:08x}","manufacturer":"Honda" if i%2 else "ACURA",
                     "eligible":i<31 or i>=46,"game_price":10000+i,"addon":i>=46,
                     "physics_sha256":"a"*64})
    return {"status":"read_only_audit","catalog":rows,"native_part_count":14557,"eligible_count":43}


class DealershipTest(unittest.TestCase):
    def test_all_eligible_once_and_native_prices_preserved(self):
        r=source()
        groups=mod.dealerships(r)
        self.assertEqual([g["manufacturer"] for g in groups],["ACURA","HONDA"])
        cars=[c for g in groups for c in g["vehicles"]]
        self.assertEqual(len(cars),43)
        self.assertEqual({c["type_index"] for c in cars},set(range(31))|set(range(46,58)))
        self.assertTrue(all(c["native_price"]==10000+c["type_index"] for c in cars))

    def test_reject_index_and_identity_changes(self):
        r=source()
        r["catalog"][46]["id"]="WRONG"
        with self.assertRaises(ValueError):
            mod.dealerships(r)

    def test_missing_manufacturer_is_not_invented(self):
        r=source()
        r["catalog"][46]["manufacturer"]=""
        group=next(g for g in mod.dealerships(r) if g["manufacturer"]=="UNASSIGNED")
        self.assertEqual(group["native_type_indices"],[46])


if __name__=="__main__":
    unittest.main()
