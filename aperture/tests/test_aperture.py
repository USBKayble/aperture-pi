"""
Basic tests for the Aperture wardriver.

Tests that modules can be imported and basic functions work.
No hardware required for these tests.
"""

import sys
import os
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from wifi_scanner import WiFiSniffer, DEFAULT_OUIS, FLOCK_IE_SIGNATURES


def test_oui_list_loaded():
    """Verify the default OUI list is populated."""
    assert len(DEFAULT_OUIS) > 0, "OUI list should not be empty"
    assert "b4:1e:52" in DEFAULT_OUIS, "Flock direct IEEE registration OUI should be present"


def test_ie_signatures_defined():
    """Verify IE fingerprint signatures are defined."""
    assert len(FLOCK_IE_SIGNATURES) > 0, "IE signatures should be defined"


def test_oui_matching():
    """Test OUI matching logic."""
    sniffer = WiFiSniffer(iface="wlan1")
    assert sniffer._match_oui("b4:1e:52:12:34:56") == True
    assert sniffer._match_oui("82:6b:f2:14:07:3a") == True
    assert sniffer._match_oui("aa:bb:cc:dd:ee:ff") == False
    assert sniffer._match_oui("") == False
    assert sniffer._match_oui("ff:ff:ff:ff:ff:ff") == False


def test_wildcard_ssid_matching():
    """Test wildcard SSID matching."""
    sniffer = WiFiSniffer(iface="wlan1")
    assert sniffer._match_wildcard_ssid("") == True
    assert sniffer._match_wildcard_ssid("Flock-ABC123") == False


def test_tshark_line_parsing():
    """Test tshark CSV line parsing."""
    sniffer = WiFiSniffer(iface="wlan1")
    # Simulate a tshark output line for a probe request
    line = "1234567890.1234\tb4:1e:52:12:34:56\t00:11:22:33:44:55\t\t0x04\t6\t2437\t-45\twlan1"
    result = sniffer._parse_tshark_line(line)
    assert result is not None, "Should parse valid probe request"
    assert result["mac"] == "b4:1e:52:12:34:56"
    assert result["subtype"] == 0x04  # probe request
    assert result["confidence_tier"] >= 3  # OUI + wildcard


def test_invalid_tshark_line():
    """Test that invalid lines return None."""
    sniffer = WiFiSniffer(iface="wlan1")
    result = sniffer._parse_tshark_line("invalid")
    assert result is None


def test_sdr_detector_config():
    """Test SDR detector configuration."""
    from sdr_detector import SDRDetector, LTE_BANDS

    assert len(LTE_BANDS) > 0, "Should have LTE bands configured"
    assert all("freq_range" in band for band in LTE_BANDS)
    assert all("name" in band for band in LTE_BANDS)


def test_database_initialization():
    """Test database can be initialized."""
    from database import Database
    import tempfile, os
    from pathlib import Path

    # Use temp file for test database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    try:
        db = Database(db_path=str(db_path))
        stats = db.get_statistics()
        assert "total_detections" in stats
        assert "unique_cameras" in stats
        db.close()
        os.unlink(str(db_path))
    except Exception:
        if os.path.exists(str(db_path)):
            os.unlink(str(db_path))
        raise


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
