import unittest
import os
import sys
import json
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).parent.parent))

from app import app
from config import database_sqlite as db_mod

class RadarSanityTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.db_path = db_mod.DB_PATH
        
    def test_db_exists(self):
        """Check if database file exists"""
        self.assertTrue(os.path.exists(self.db_path), f"Database not found at {self.db_path}")

    def test_api_dashboard_basic(self):
        """Test if dashboard API returns 200 and basic structure"""
        response = self.client.get('/api/dashboard')
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.data)
        expected_keys = ["stats", "signals", "market", "wards_by_city", "trend_data"]
        for key in expected_keys:
            self.assertIn(key, data, f"Missing key '{key}' in API response")
            
        # Check stats serialization
        self.assertIsInstance(data["stats"], dict)
        self.assertIn("total", data["stats"])
        self.assertIn("signals", data["stats"])

    def test_mos_filtering(self):
        """Test if MOS (Mức độ ngợp) filter affects signal count"""
        # Get count with 0% MOS
        res0 = self.client.get('/api/dashboard?mos_min=0')
        count0 = json.loads(res0.data)["stats"]["signals"]

        # Get count with 50% MOS (should be less or equal)
        res50 = self.client.get('/api/dashboard?mos_min=50')
        count50 = json.loads(res50.data)["stats"]["signals"]
        
        self.assertLessEqual(count50, count0, "MOS 50% should have fewer or equal signals than MOS 0%")

    def test_prop_type_filtering(self):
        """Test if property type filtering works"""
        # Request only 'nha_dat'
        res = self.client.get('/api/dashboard?prop_type=nha_dat')
        data = json.loads(res.data)
        
        for sig in data["signals"]:
            self.assertEqual(sig["prop_type"], "nha_dat", f"Listing {sig['id']} has wrong prop_type")

    def test_sorting(self):
        """Test if sorting by price works"""
        res = self.client.get('/api/dashboard?sort_by=ppm2_low')
        data = json.loads(res.data)
        signals = data["signals"]
        
        if len(signals) > 1:
            # Check if prices are non-decreasing
            prices = [s["actual_ppm2"] for s in signals if s["actual_ppm2"] > 0]
            self.assertEqual(prices, sorted(prices), "Signals are not sorted by price per m2 ASC")

    def test_heatmap_api(self):
        """Test if heatmap API works"""
        response = self.client.get('/api/heatmap')
        self.assertEqual(response.status_code, 200)

if __name__ == '__main__':
    unittest.main()
