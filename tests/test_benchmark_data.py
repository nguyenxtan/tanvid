import unittest
import io
import wave
import struct
from backend.benchmark_data import ForwardReader, parse_textgrid, select_excerpt


class ReferenceTests(unittest.TestCase):
    def test_wav_with_extra_chunks_from_forward_only_archive(self):
        output=io.BytesIO()
        with wave.open(output,'wb') as wav:
            wav.setparams((1,2,16000,16,'NONE','not compressed'));wav.writeframes(b'\0'*32)
        raw=output.getvalue()
        # Insert a real unknown RIFF chunk before the data chunk.
        raw=raw[:36]+b'JUNK'+struct.pack('<I',4)+b'abcd'+raw[36:]
        raw=raw[:4]+struct.pack('<I',len(raw)-8)+raw[8:]
        with wave.open(ForwardReader(io.BytesIO(raw)),'rb') as wav:
            self.assertEqual(wav.getframerate(),16000)
            self.assertEqual(wav.readframes(16),b'\0'*32)

    def test_publisher_intervals_and_clean_boundary(self):
        text='''File type = "ooTextFile"
item [1]:
 class = "IntervalTier"
 name = "speaker-A"
 intervals [1]:
  xmin = 0
  xmax = 130
  text = "你好，中国。"
 intervals [2]:
  xmin = 140
  xmax = 181
  text = "不能截断"
item [2]:
 class = "IntervalTier"
 name = "speaker-B"
 intervals [1]:
  xmin = 120
  xmax = 129
  text = "是的"
'''
        intervals=parse_textgrid(text)
        reference=select_excerpt(intervals)
        self.assertEqual(reference['end_seconds'],130)
        self.assertEqual(reference['text'],'你好，中国。是的')
        self.assertEqual(reference['overlap_seconds'],9)
        self.assertEqual(len(reference['speakers']),2)

    def test_no_reference_or_no_safe_boundary_is_rejected(self):
        with self.assertRaises(ValueError):parse_textgrid('No transcript')
        with self.assertRaises(ValueError):select_excerpt([{'start':0,'end':190,'speaker':'A','text':'不能截断'}])


if __name__=='__main__':unittest.main()
