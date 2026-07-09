import unittest

from services.api.app.matchers import match_job


class MatchingTest(unittest.TestCase):
    def sample_job(self):
        return {
            "title": "产品经理",
            "cities": ["上海", "北京"],
            "degree_min": "bachelor",
            "source_level": "A",
            "campaign": {
                "accepts_overseas": True,
                "overseas_grad_start": "2025-09",
                "overseas_grad_end": "2026-08",
                "domestic_grad_start": "2025-09",
                "domestic_grad_end": "2026-08",
                "degree_min": "bachelor",
                "source_level": "A",
            },
            "process_rule": {
                "written_test_status": "no_unified_written_test",
                "written_test_burden": 1,
            },
        }

    def test_overseas_eligible(self):
        profile = {
            "graduation_date": "2026-08",
            "school_region": "overseas",
            "degree": "master",
            "target_cities": ["上海"],
            "max_written_test_burden": 1,
        }
        result = match_job(profile, self.sample_job())
        self.assertEqual(result["status"], "eligible")
        self.assertGreater(result["score"], 0.8)

    def test_overseas_grad_not_eligible(self):
        profile = {
            "graduation_date": "2027-01",
            "school_region": "overseas",
            "degree": "master",
            "target_cities": ["上海"],
            "max_written_test_burden": 1,
        }
        result = match_job(profile, self.sample_job())
        self.assertEqual(result["status"], "not_eligible")
        self.assertTrue(result["blockers"])

    def test_written_test_blocker(self):
        profile = {
            "graduation_date": "2026-08",
            "school_region": "overseas",
            "degree": "master",
            "target_cities": ["上海"],
            "max_written_test_burden": 0,
        }
        result = match_job(profile, self.sample_job())
        self.assertEqual(result["status"], "not_eligible")


if __name__ == "__main__":
    unittest.main()
