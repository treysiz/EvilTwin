import unittest

from app import freq_to_channel, parse_iwlist_scan


class IwlistParserTest(unittest.TestCase):
    def test_parse_wpa2_network(self):
        output = """
          Cell 01 - Address: AA:BB:CC:DD:EE:FF
                    Channel:6
                    Frequency:2.437 GHz (Channel 6)
                    Quality=70/70  Signal level=-39 dBm
                    Encryption key:on
                    ESSID:"xinhome"
                    IE: IEEE 802.11i/WPA2 Version 1
        """

        aps = parse_iwlist_scan(output)

        self.assertEqual(len(aps), 1)
        self.assertEqual(aps[0]["ssid"], "xinhome")
        self.assertEqual(aps[0]["bssid"], "AA:BB:CC:DD:EE:FF")
        self.assertEqual(aps[0]["channel"], 6)
        self.assertEqual(aps[0]["frequency"], 2437)
        self.assertEqual(aps[0]["signal"], -39)
        self.assertEqual(aps[0]["security"], "WPA2")

    def test_parse_open_hidden_network(self):
        output = """
          Cell 02 - Address: 11:22:33:44:55:66
                    Frequency:5.18 GHz (Channel 36)
                    Quality=35/70
                    Encryption key:off
                    ESSID:""
        """

        aps = parse_iwlist_scan(output)

        self.assertEqual(len(aps), 1)
        self.assertEqual(aps[0]["ssid"], "<隐藏>")
        self.assertEqual(aps[0]["channel"], 36)
        self.assertEqual(aps[0]["frequency"], 5180)
        self.assertEqual(aps[0]["security"], "OPEN")

    def test_freq_to_channel_handles_24_5_and_6ghz(self):
        self.assertEqual(freq_to_channel(2437), 6)
        self.assertEqual(freq_to_channel(5180), 36)
        self.assertEqual(freq_to_channel(5975), 5)


if __name__ == "__main__":
    unittest.main()
