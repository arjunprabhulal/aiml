import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from library_multimodal import figure_documents,image_blocks,pixel_hash
ROOT=Path(__file__).parent
class ImageTests(unittest.TestCase):
    def test_selected_images_match_retained_pixel_hashes(self):
        for doc in figure_documents():self.assertEqual(pixel_hash(ROOT/doc.metadata['image']),doc.metadata['pixel_sha256'])
    def test_changed_pixels_are_refused_before_a_model_call(self):
        doc=figure_documents()[0]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'changed.png'
            with Image.open(ROOT/doc.metadata['image']) as image:
                image=image.convert('L'); image.putpixel((0,0),127); image.save(path)
            doc.metadata['image']=str(path)
            with self.assertRaisesRegex(ValueError,'pixels changed'):image_blocks([doc])
    def test_identical_pixels_with_different_png_compression_match(self):
        doc=figure_documents()[0]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'recompressed.png'
            with Image.open(ROOT/doc.metadata['image']) as image:image.save(path,compress_level=0)
            self.assertEqual(pixel_hash(path),doc.metadata['pixel_sha256'])
    def test_each_image_is_preceded_by_its_source_id(self):
        docs=figure_documents(); blocks=image_blocks(docs)
        self.assertEqual(len(blocks),len(docs)*2)
        for i,doc in enumerate(docs):
            self.assertIn(doc.id,blocks[i*2]['text']); self.assertEqual(blocks[i*2+1]['type'],'image_url')
    def test_description_only_run_abstained_and_image_run_read_chart(self):
        run=json.loads((ROOT/'library-image-run.json').read_text())
        text,image=run['results']
        self.assertEqual(text['answer']['status'],'not_in_sources')
        self.assertIn('380',image['answer']['answer']);self.assertIn('medium',image['answer']['answer'].lower())
    def test_grayscale_hash_can_miss_a_color_only_change(self):
        with tempfile.TemporaryDirectory() as directory:
            red=Path(directory)/'red.png'
            gray=Path(directory)/'gray.png'
            Image.new('RGB',(1,1),(255,0,0)).save(red)
            Image.new('RGB',(1,1),(76,76,76)).save(gray)
            self.assertNotEqual(red.read_bytes(),gray.read_bytes())
            self.assertEqual(pixel_hash(red),pixel_hash(gray))
if __name__=='__main__':unittest.main(verbosity=2)
