import io, os, sys, unittest, zipfile
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from nace_importer import parse_rdf, format_raw_code, validate_source, code_level, EXPECTED

SAMPLE_RDF = """<?xml version="1.0" encoding="utf-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:skos="http://www.w3.org/2004/02/skos/core#"
         xmlns:xml="http://www.w3.org/XML/1998/namespace">
  <rdf:Description rdf:about="http://data.europa.eu/ux2/nace2.1/J">
    <skos:notation>J</skos:notation>
    <skos:prefLabel xml:lang="fr">Information et communication</skos:prefLabel>
    <skos:prefLabel xml:lang="de">Information und Kommunikation</skos:prefLabel>
    <skos:prefLabel xml:lang="en">Information and communication</skos:prefLabel>
  </rdf:Description>
  <rdf:Description rdf:about="http://data.europa.eu/ux2/nace2.1/62">
    <skos:notation>62</skos:notation>
    <skos:broader rdf:resource="http://data.europa.eu/ux2/nace2.1/J"/>
    <skos:prefLabel xml:lang="fr">Programmation, conseil et autres activites informatiques</skos:prefLabel>
    <skos:prefLabel xml:lang="de">Erbringung von Dienstleistungen der Informationstechnologie</skos:prefLabel>
    <skos:prefLabel xml:lang="en">Computer programming, consultancy and related activities</skos:prefLabel>
  </rdf:Description>
  <rdf:Description rdf:about="http://data.europa.eu/ux2/nace2.1/62.1">
    <skos:notation>62.1</skos:notation>
    <skos:broader rdf:resource="http://data.europa.eu/ux2/nace2.1/62"/>
    <skos:prefLabel xml:lang="fr">Programmation informatique</skos:prefLabel>
    <skos:prefLabel xml:lang="de">Programmierungstaetigkeiten</skos:prefLabel>
    <skos:prefLabel xml:lang="en">Computer programming activities</skos:prefLabel>
  </rdf:Description>
  <rdf:Description rdf:about="http://data.europa.eu/ux2/nace2.1/62.10">
    <skos:notation>62.10</skos:notation>
    <skos:broader rdf:resource="http://data.europa.eu/ux2/nace2.1/62.1"/>
    <skos:prefLabel xml:lang="fr">Programmation informatique</skos:prefLabel>
    <skos:prefLabel xml:lang="de">Programmierungstaetigkeiten</skos:prefLabel>
    <skos:prefLabel xml:lang="en">Computer programming activities</skos:prefLabel>
    <skos:scopeNote xml:lang="fr">Comprend l'ecriture, la modification, le test et le support de logiciels.</skos:scopeNote>
  </rdf:Description>
  <rdf:Description rdf:about="http://data.europa.eu/ux2/nace2.1/NACE2.1_NACE2_62.10_62.01">
    <sourceConcept rdf:resource="http://data.europa.eu/ux2/nace2.1/62.10"/>
    <targetConcept rdf:resource="http://data.europa.eu/ux2/nace2/6201"/>
    <mapping_cardinality rdf:resource="http://data.europa.eu/ux2/nace2.1/1_1"/>
  </rdf:Description>
</rdf:RDF>
""".encode('utf-8')

class OfficialNaceImporterTests(unittest.TestCase):
    def test_parse_rdf_sample(self):
        bio = io.BytesIO(SAMPLE_RDF)
        parsed = parse_rdf(bio, ('fr', 'de', 'en'))
        self.assertEqual(len(parsed['items']), 4)
        levels = {x['code']: x['level'] for x in parsed['items']}
        self.assertEqual(levels['J'], 'SECTION')
        self.assertEqual(levels['62'], 'DIVISION')
        self.assertEqual(levels['62.1'], 'GROUP')
        self.assertEqual(levels['62.10'], 'CLASS')
        self.assertEqual(len(parsed['labels']), 12)
        self.assertEqual(len(parsed['notes']), 1)
        self.assertEqual(len(parsed['correspondences']), 1)
        self.assertEqual(parsed['correspondences'][0]['source_code'], '62.01')
        self.assertEqual(parsed['correspondences'][0]['target_code'], '62.10')

    def test_code_level_hierarchy(self):
        self.assertEqual(code_level('A'), 'SECTION')
        self.assertEqual(code_level('01'), 'DIVISION')
        self.assertEqual(code_level('01.1'), 'GROUP')
        self.assertEqual(code_level('01.11'), 'CLASS')
        self.assertIsNone(code_level('INVALID_CODE'))

    def test_rev2_raw_codes_are_formatted(self):
        self.assertEqual(format_raw_code('0111'), '01.11')
        self.assertEqual(format_raw_code('011'), '01.1')
        self.assertEqual(format_raw_code('01'), '01')
        self.assertEqual(format_raw_code('A'), 'A')

    def test_validate_source_guards(self):
        valid = 'https://showvoc.op.europa.eu/semanticturkey/downloads/ESTAT_Classification/distributions/NACE_Rev_2.1.zip'
        validate_source(valid)
        with self.assertRaises(ValueError):
            validate_source('https://malicious.example.com/NACE_Rev_2.1.zip')
        with self.assertRaises(ValueError):
            validate_source('http://showvoc.op.europa.eu/semanticturkey/downloads/NACE_Rev_2.1.zip')

if __name__ == '__main__':
    unittest.main()
