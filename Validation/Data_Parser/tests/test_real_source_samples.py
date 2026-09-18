import unittest

from Validation.Data_Parser.app.models.common import ParserEnvelope
from Validation.Data_Parser.app.parsers.sais import SAISParser
from Validation.Data_Parser.app.parsers.msis import MSISParser
from Validation.Data_Parser.app.parsers.lrit import LRITParser
from Validation.Data_Parser.app.parsers.vatms import VATMSParser
from Validation.Data_Parser.app.parsers.nais import NAISParser


class TestRealSourceSamples(unittest.TestCase):
    def envelope(self, source, payload):
        return ParserEnvelope(
            message_id="sample-1",
            source=source,
            input_type="FILE",
            received_at="2026-06-25T14:22:00Z",
            payload=payload,
        )

    def test_sais_single_line(self):
        line = r"\s:66,c:1782377468*4C\!AIVDM,1,1,,B,177hgW001bWc5el;kRfmHl@<00SR,0*47"
        result = SAISParser().parse(self.envelope("SAIS_IOR", line))
        self.assertEqual(result.records_parsed, 1)
        self.assertEqual(result.records[0].app_message_id, 1)
        self.assertIsNotNone(result.records[0].latitude)

    def test_sais_multipart_physical_line_contract(self):
        first = r"\g:1-2-3032148,s:66,c:1782377418*06\!AIVDM,2,1,8,B,5714j:02<CB<7HG?3CML4@V04j0H4V222222220l0" + chr(96) + r"D545Ide:QUBPBD,0*74"
        second = r"\g:2-2-3032148*62\!AIVDM,2,2,8,B,PB>p5KPKQCBDPE0,2*17"
        result = SAISParser().parse(self.envelope("SAIS_IOR", first + "\n" + second))
        self.assertEqual(result.records_parsed, 2)
        self.assertEqual(result.records[0].raw_attributes.get("complete_decode"), False)
        self.assertTrue(result.records[1].mmsi)

    def test_msis_real_header(self):
        payload = (
            "mmsi,latitude,longitude,sog,cog,true_heading,rate_of_turn,navigatetion_status,updated,source_name,classb_flag,ship_name,imo,callsign,length,width,draught,destination,type_and_cargo,eta\n"
            "304944000,51.248917,4.4042835,0.0,332.2,151.0,3.6158633,5,1780295512,MSSIS,0,ALREK,9330953,V2BW4,0.0,0.0,6.0,BEANR,70,1900-01-01 00:00:00"
        )
        result = MSISParser().parse(self.envelope("MSIS", payload))
        self.assertEqual(result.records_parsed, 1)
        self.assertEqual(result.records[0].imo, 9330953)
        self.assertEqual(result.records[0].destination, "BEANR")

    def test_lrit_real_row(self):
        payload = "419000122,13.107333,80.302667,None,None,None,None,None,2026-06-03 04:04:49.218+00,lrit,None,OCEAN FAME,9448542,None,None,None,None,None,Ocean Going,None"
        result = LRITParser().parse(self.envelope("LRIT", payload))
        self.assertEqual(result.records_parsed, 1)
        self.assertEqual(result.records[0].mmsi, 419000122)
        self.assertEqual(result.records[0].imo, 9448542)

    def test_vatms_east_real_line(self):
        line = "!WSVDM,1,1,1,A,1=JDkShP005p6<f9J=4rS8L60000,0*29"
        result = VATMSParser().parse(self.envelope("VATMS_EAST", line))
        self.assertEqual(result.records_parsed, 1)

    def test_vatms_west_bad_checksum_is_rejected(self):
        line = "$TMVTD,230726,103413.05,R,0327,1239,1831.9035,N,07216.6640,E,000.0,T,000.0,N,,,,,,,,,,,0,0,,,,,0,T*00"
        result = VATMSParser().parse(self.envelope("VATMS_WEST", line))
        self.assertEqual(result.records_parsed, 0)
        self.assertEqual(result.records_rejected, 1)

    def test_vatms_west_real_rich_line(self):
        line = "$TMVTD,230726,103414.03,R,0282,GREATSHIP ROOPA,1834.4993,N,07212.4962,E,210.6,T,003.1,N,NSC Cleared Vessel,AVWE,7800,1700,580,,419000621,2200,-250,9570761,0,0,99,9,HEERA FLD           ,07162000,1,T*5F"
        result = VATMSParser().parse(self.envelope("VATMS_WEST", line))
        self.assertEqual(result.records_parsed, 1)
        self.assertEqual(result.records[0].mmsi, 419000621)
        self.assertEqual(result.records[0].imo, 9570761)

    def test_nais_vessel_and_status_lines(self):
        payload = (
            "!ABVDO,1,1,,,4h3wotiuK3bHU5KQBB6:dfG00000,0*20\n"
            "$ABVSI,North Point,2,102437.043072,1389,-79,36*54"
        )
        result = NAISParser().parse(self.envelope("NAIS", payload))
        self.assertEqual(result.records_parsed, 1)


if __name__ == "__main__":
    unittest.main()
