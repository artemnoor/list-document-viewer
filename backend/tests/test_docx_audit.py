"""Regressions for real DOCX structures found in calibre's public demo file.

Native extraction must retain note bodies, hyperlink destinations, list semantics,
inline image metadata, and nested-table content. No model downloads are required.
"""
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from lxml import etree, html
from PIL import Image
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE as RT

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extraction import native_parts
from markdown_export import preview_html, structured_markdown

W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
REL='http://schemas.openxmlformats.org/package/2006/relationships'
CT='http://schemas.openxmlformats.org/package/2006/content-types'


def numbering(document, num_id, num_format):
    root=document.part.numbering_part.element
    abstract=OxmlElement('w:abstractNum');abstract.set(qn('w:abstractNumId'),str(num_id))
    for depth in (0,1):
        level=OxmlElement('w:lvl');level.set(qn('w:ilvl'),str(depth))
        for tag,value in [('start','1'),('numFmt',num_format),('lvlText','•' if num_format=='bullet' else '%'+str(depth+1)+'.')]:
            child=OxmlElement('w:'+tag);child.set(qn('w:val'),value);level.append(child)
        abstract.append(level)
    root.append(abstract)
    num=OxmlElement('w:num');num.set(qn('w:numId'),str(num_id))
    reference=OxmlElement('w:abstractNumId');reference.set(qn('w:val'),str(num_id));num.append(reference);root.append(num)


def list_paragraph(document,text,num_id,depth=0):
    paragraph=document.add_paragraph(text)
    props=paragraph._p.get_or_add_pPr();num=OxmlElement('w:numPr')
    for tag,value in [('ilvl',depth),('numId',num_id)]:
        child=OxmlElement('w:'+tag);child.set(qn('w:val'),str(value));num.append(child)
    props.append(num)
    return paragraph


def note_fixture(path):
    document=Document();paragraph=document.add_paragraph('The main document text')
    for kind in ('footnote','endnote'):
        run=OxmlElement('w:r');reference=OxmlElement('w:'+kind+'Reference');reference.set(qn('w:id'),'1');run.append(reference);paragraph._p.append(run)
    document.save(path)
    with ZipFile(path) as archive: package={name:archive.read(name) for name in archive.namelist()}
    relationships=etree.fromstring(package['word/_rels/document.xml.rels'])
    types=etree.fromstring(package['[Content_Types].xml'])
    for kind,text in [('footnote','Important footnote body.'),('endnote','Important endnote body.')]:
        root=etree.Element('{'+W+'}'+kind+'s',nsmap={'w':W})
        note=etree.SubElement(root,'{'+W+'}'+kind);note.set('{'+W+'}id','1')
        p=etree.SubElement(note,'{'+W+'}p');r=etree.SubElement(p,'{'+W+'}r');t=etree.SubElement(r,'{'+W+'}t');t.text=text
        package['word/'+kind+'s.xml']=etree.tostring(root,xml_declaration=True,encoding='UTF-8')
        relation=etree.SubElement(relationships,'{'+REL+'}Relationship');relation.set('Id','rIdAudit'+kind);relation.set('Type',RT.FOOTNOTES if kind=='footnote' else RT.ENDNOTES);relation.set('Target',kind+'s.xml')
        content=etree.SubElement(types,'{'+CT+'}Override');content.set('PartName','/word/'+kind+'s.xml');content.set('ContentType','application/vnd.openxmlformats-officedocument.wordprocessingml.'+kind+'s+xml')
    package['word/_rels/document.xml.rels']=etree.tostring(relationships,xml_declaration=True,encoding='UTF-8')
    package['[Content_Types].xml']=etree.tostring(types,xml_declaration=True,encoding='UTF-8')
    with ZipFile(path,'w',ZIP_DEFLATED) as archive:
        for name,data in package.items():archive.writestr(name,data)


class DocxAudit(unittest.TestCase):
    def setUp(self):self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name)
    def tearDown(self):self.temporary.cleanup()

    def test_note_bodies_survive_extraction_and_markdown(self):
        path=self.root/'notes.docx';note_fixture(path)
        parts=native_parts(path,'.docx');exported=structured_markdown({'parts':parts})
        for text in ('Important footnote body.','Important endnote body.'):
            self.assertIn(text,str(parts))
            self.assertEqual(exported.count(text),1)
        self.assertIn('The main document text',exported)

    def test_external_hyperlink_keeps_target(self):
        document=Document();paragraph=document.add_paragraph('Open ')
        link=OxmlElement('w:hyperlink');link.set(qn('r:id'),document.part.relate_to('https://example.org/full-report',RT.HYPERLINK,is_external=True))
        run=OxmlElement('w:r');text=OxmlElement('w:t');text.text='the report';run.append(text);link.append(run);paragraph._p.append(link)
        path=self.root/'hyperlink.docx';document.save(path)
        parts=native_parts(path,'.docx');exported=structured_markdown({'parts':parts})
        self.assertIn('the report',exported)
        self.assertIn('https://example.org/full-report',exported)

    def test_numbered_bulleted_and_nested_lists_survive(self):
        document=Document();numbering(document,100,'decimal');numbering(document,101,'bullet')
        list_paragraph(document,'First ordered item',100);list_paragraph(document,'Second ordered item',100)
        document.add_paragraph('Separate lists')
        list_paragraph(document,'Top bullet',101);list_paragraph(document,'Nested bullet',101,1)
        path=self.root/'lists.docx';document.save(path)
        parts=native_parts(path,'.docx');rendered=preview_html(structured_markdown({'parts':parts}))
        tree=html.fromstring(rendered)
        self.assertTrue(tree.xpath('//ol/li[contains(.,"First ordered item")]'))
        self.assertTrue(tree.xpath('//ul/li[contains(.,"Top bullet")]/ul/li[contains(.,"Nested bullet")]'))

    def test_inline_image_alt_metadata_is_not_silently_dropped(self):
        document=Document();document.add_paragraph('Before diagram')
        image=Image.new('RGB',(30,20),'white');buffer=BytesIO();image.save(buffer,format='PNG');buffer.seek(0)
        shape=document.add_picture(buffer);shape._inline.docPr.set('descr','Diagram description')
        document.add_paragraph('After diagram')
        path=self.root/'image.docx';document.save(path)
        parts=native_parts(path,'.docx')
        self.assertTrue(any(part.get('kind')=='picture' for part in parts))
        self.assertIn('Diagram description',str(parts))

    def test_nested_table_text_is_preserved_once(self):
        document=Document();outer=document.add_table(rows=1,cols=1);outer.cell(0,0).text='Outer cell'
        nested=outer.cell(0,0).add_table(rows=1,cols=1);nested.cell(0,0).text='Unique nested value'
        path=self.root/'nested.docx';document.save(path)
        parts=native_parts(path,'.docx');exported=structured_markdown({'parts':parts})
        self.assertEqual(exported.count('Unique nested value'),1)
        self.assertEqual(preview_html(exported).count('<table>'),2)


if __name__=='__main__':unittest.main()
