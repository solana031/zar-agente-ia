import unittest, io
from app.document_renderer import render_pdf
from pypdf import PdfReader
class DocumentRendererTests(unittest.TestCase):
 def test_templates_links_and_long_table(self):
  for kind in ['RESEARCH','PROPOSAL','BUSINESS','FINANCIAL','EXECUTIVE']:
   text='# Resumen\nMuestra interna sin ingresos reales.\n# Datos\nConcepto\tEstado\n'+ '\n'.join('Fila '+str(i)+'\tSin datos' for i in range(80))
   data=render_pdf('Informe de prueba',text,kind,[{'title':'Fuente de prueba','url':'https://example.com'}]);reader=PdfReader(io.BytesIO(data))
   self.assertGreater(len(reader.pages),1);self.assertIn('Fila 79',''.join(p.extract_text() for p in reader.pages));self.assertTrue(any(p.get('/Annots') for p in reader.pages));self.assertIn('PÃ¡gina 1',reader.pages[0].extract_text())
if __name__=='__main__':unittest.main()
