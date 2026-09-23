import importlib
import unittest

class StandaloneParserTests(unittest.TestCase):
    def test_sais_ior(self):
        m=importlib.import_module("Validation.Feeds.SAIS_IOR")
        rows=m.parse_lines([r"\s:66,c:1782377468*4C\!AIVDM,1,1,,B,177hgW001bWc5el;kRfmHl@<00SR,0*47"])
        self.assertEqual(len(rows),1); self.assertIsNotNone(rows[0].mmsi)

    def test_sais_global(self):
        m=importlib.import_module("Validation.Feeds.SAIS_GLOBAL")
        rows=m.parse_lines([r"\s:66,c:1782377429*1E\!AIVDM,1,1,,,3:U6vSO028MFm<=qgJt7oV6n01:P,0*2F"])
        self.assertEqual(len(rows),1)

    def test_msis(self):
        m=importlib.import_module("Validation.Feeds.MSIS")
        rows=m.parse_msis(["mmsi,latitude,longitude,sog,cog,true_heading,rate_of_turn,navigatetion_status,updated,source_name,classb_flag,ship_name,imo,callsign,length,width,draught,destination,type_and_cargo,eta",
        "219023392,55.21642,11.742363,0.0,213.4,511.0,0.0,15,1780295512,MSSIS,0,MERETE,0,,0.0,0.0,0.0,,0,1900-01-01 00:00:00"])
        self.assertEqual(len(rows),1);self.assertEqual(rows[0].mmsi,219023392)

    def test_lrit(self):
        m=importlib.import_module("Validation.Feeds.LRIT")
        rows=m.parse_lrit(["419000122,13.107333,80.302667,None,None,None,None,None,2026-06-03 04:04:49.218+00,lrit,None,OCEAN FAME,9448542,None,None,None,None,None,Ocean Going,None"])
        self.assertEqual(len(rows),1);self.assertEqual(rows[0].imo,9448542)

    def test_vatms_east(self):
        m=importlib.import_module("Validation.Feeds.VATMS_EAST")
        rows=m.parse_vatms_east(["!WSVDM,1,1,1,A,1=JDkShP005p6<f9J=4rS8L60000,0*29"])
        self.assertEqual(len(rows),1)

    def test_vatms_west(self):
        m=importlib.import_module("Validation.Feeds.VATMS_WEST")
        rows=m.parse_vatms_west(["$TMVTD,230726,103413.05,R,0329,WATER LILY,1856.9488,N,07254.9815,E,323.1,T,000.2,N,Tug,AVQX,3100,1100,450,,419000482,,,9620865,0,0,,9,,,1,T*74"])
        self.assertEqual(len(rows),1);self.assertEqual(rows[0].mmsi,419000482);self.assertEqual(rows[0].imo,9620865)

    def test_nais(self):
        m=importlib.import_module("Validation.Feeds.NAIS")
        rows=m.parse_nais(["!ABVDO,1,1,,,4h3wotiuK3bHU5KQBB6:dfG00000,0*20","$ABVSI,North Point,2,102437.043072,1389,-79,36*54"])
        self.assertEqual(len(rows),1)

    def test_xml_contract(self):
        m=importlib.import_module("Validation.Feeds.SAIS_IOR")
        r=m.R(timestamp="2026-06-25T00:00:00Z",mmsi=419000482,imo=9620865,callsign="AVQX",vessel_name="WATER LILY",
              vessel_type=52,latitude=18.949,cog=323.1,sog=0.2,true_heading=None,length=31.0,width=11.0,draught=4.5)
        r.cat_identity=3;r.foreign_track_number=r.mmsi;r.vessel_remarks="TEST"
        logical=m.logical(r,1780000000000,r.mmsi,38)
        x=m.xml(logical)
        self.assertIn("<id>id.mmsi</id>",x)
        self.assertIn("<id>vessel.remarks</id>",x)
        self.assertEqual(x.count("<ns2:XTrack"),1)

if __name__=="__main__":
    unittest.main()
