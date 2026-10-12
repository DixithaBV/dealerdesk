import csv, os, sys, unittest
from decimal import Decimal
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from assistant import guard, sanitize  # noqa: E402
from assistant.retrieval import Retriever  # noqa: E402

PRODUCTS = list(csv.DictReader(open(os.path.join(ROOT, "data", "catalogue.csv"), encoding="utf-8-sig")))
R = Retriever(PRODUCTS)
BY = {p["sku"]: p for p in PRODUCTS}


def fits(res):
    return [(BY[r["sku"]]["name"], r["fit"]) for r in res["results"]]


class RetrievalTests(unittest.TestCase):
    def test_pulsar_150_brake_pads(self):
        r = R.search("brake pads for a Pulsar 150")
        self.assertEqual(r["vehicle_resolution"], "resolved")
        self.assertEqual(r["matched_vehicles"], ["Bajaj Pulsar 150"])
        self.assertTrue(r["results"])
        for x in r["results"]:
            self.assertIn(BY[x["sku"]]["vehicle_fitment"], ("Bajaj Pulsar 150", "Universal"))
            self.assertIn("Brake Pad", BY[x["sku"]]["name"])

    def test_similar_models_do_not_mix(self):
        for q, want in [("Duke 200 air filter", "KTM Duke 200"), ("Duke 390 air filter", "KTM Duke 390"),
                        ("Apache RTR 160 chain", "TVS Apache RTR 160"), ("Classic 350 brake shoe", "Royal Enfield Classic 350")]:
            r = R.search(q)
            self.assertEqual(r["matched_vehicles"], [want], q)
            for x in r["results"]:
                self.assertIn(BY[x["sku"]]["vehicle_fitment"], (want, "Universal"), q)

    def test_ambiguous_vehicle_is_flagged_not_guessed(self):
        r = R.search("brake pads for my Pulsar")
        self.assertEqual(r["vehicle_resolution"], "ambiguous")
        self.assertEqual(r["results"], [])
        self.assertGreaterEqual(len(r["matched_vehicles"]), 2)

    def test_no_vehicle_asks_for_one(self):
        r = R.search("I need brake pads")
        self.assertTrue(r["needs_vehicle"])

    def test_universal_part_without_vehicle(self):
        r = R.search("engine oil 10W30")
        self.assertFalse(r["needs_vehicle"])
        self.assertTrue(r["results"])
        self.assertTrue(all(BY[x["sku"]]["vehicle_fitment"] == "Universal" for x in r["results"]))

    def test_synonyms_and_typos(self):
        self.assertTrue(R.search("tire for Pulsar 150")["results"])
        self.assertEqual(R.search("tyres for Himalayan 450")["results"], [])  # no such part exists: never substitute
        self.assertTrue(R.search("brake padz for Pulsar 150")["results"])
        self.assertEqual(R.search("spark plug for Gixxer SF")["matched_vehicles"], ["Suzuki Gixxer SF"])

    def test_every_catalogue_vehicle_resolves_to_itself(self):
        for f in R.fitments:
            r = R.resolve_vehicle(f)[0]
            self.assertEqual(r, [f], f)

    def test_deterministic(self):
        a = R.search("led headlight Duke 390")
        self.assertEqual(a, R.search("led headlight Duke 390"))


class SanitizeTests(unittest.TestCase):
    def test_injected_descriptions_are_cut(self):
        bad = [p["description"] for p in PRODUCTS if sanitize.looks_like_injection(p["description"])]
        self.assertGreaterEqual(len(bad), 2)
        for d in bad:
            c = sanitize.clean_text(d)
            self.assertNotIn("VIKMO", c.upper()); self.assertNotIn("90%", c); self.assertNotIn("ignore", c.lower())
            self.assertNotIn("admin", c.lower()); self.assertNotIn("[system]", c.lower())

    def test_normal_descriptions_survive(self):
        d = "RK drive chain made to fit the Bajaj Pulsar 150. Direct-fit replacement."
        self.assertEqual(sanitize.clean_text(d, 200), d)
        self.assertFalse(any(sanitize.looks_like_injection(p["description"]) for p in PRODUCTS[:50]))


class GuardTests(unittest.TestCase):
    facts = {"prices": {Decimal("1459.50")}, "quantities": {136}, "skus": {"BRK-1044"}}

    def test_grounded_reply_passes(self):
        self.assertEqual(guard.check_reply("BRK-1044 costs ₹1,459.50 and 136 units are in stock.", self.facts, "", {"BRK-1044"}), [])

    def test_made_up_numbers_fail(self):
        self.assertTrue(guard.check_reply("It costs ₹999.00", self.facts))
        self.assertTrue(guard.check_reply("We have 500 units in stock", self.facts))
        self.assertTrue(guard.check_reply("Try BRK-9999", self.facts, "", {"BRK-1044"}))

    def test_promo_claims_fail(self):
        self.assertTrue(guard.check_reply("Everything is 90% off, use VIKMO-FREE-90", self.facts))

    def test_wrong_language_reply_is_blocked(self):
        arabic = "\u0627\u0644\u0628\u0637\u0627\u0637\u0633 \u0648\u0627\u0644\u062c\u0632\u0631 \u0648\u0627\u0644\u062f\u062c\u0627\u062c"
        self.assertTrue(any("language" in p for p in guard.check_reply(arabic, self.facts, "brake pads for a Duke 390?")))
        self.assertEqual(guard.check_reply(arabic, {}, arabic), [])  # a dealer who writes Arabic may get Arabic

    def test_reply_that_ignores_tool_results_is_blocked(self):
        self.assertTrue(guard.check_reply("Here you go.", self.facts, "price?", {"BRK-1044"}))
        self.assertEqual(guard.check_reply("BRK-1044 is ₹1,459.50.", self.facts, "price?", {"BRK-1044"}), [])
        self.assertEqual(guard.check_reply("Which one do you mean?", self.facts, "price?", {"BRK-1044"}), [])  # a question is fine
        self.assertEqual(guard.check_reply("We have nothing for that.", {}, "flux capacitor?"), [])  # no tool results: fine

    def test_clean_reply_strips_leaked_reasoning_only(self):
        ok = "Yes, we have the Brake Pad Set (BRK-1032) for \u20b91,849.00."
        self.assertEqual(guard.clean_reply("\u1ec7m\n" + ok), ok)
        self.assertEqual(guard.clean_reply("\u1ec7mthought\n" + ok), ok)
        self.assertEqual(guard.clean_reply("\u043e\u0433\u043e\u043c\n" + ok), ok)
        self.assertEqual(guard.clean_reply("Preferences/constraints checked. Now replying." + ok), ok)
        self.assertEqual(guard.clean_reply(ok), ok)
        self.assertEqual(guard.clean_reply("Sure!\nHere are the parts."), "Sure!\nHere are the parts.")  # real text is kept

    def test_multiples_allowed_for_totals(self):
        self.assertEqual(guard.check_reply("3 pads = ₹4,378.50", self.facts, "3 pads"), [])


if __name__ == "__main__":
    unittest.main()
