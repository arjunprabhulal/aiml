"""Verify the selected source facts only on an actual Python3.12 interpreter."""
from pathlib import Path
import platform,sys,inspect,tempfile,json

def main():
    if sys.version_info[:2]!=(3,12):raise RuntimeError("This recorded behavior probe requires Python3.12; other versions were not executed for this record.")
    with tempfile.TemporaryDirectory()as tmp:
        file=Path(tmp)/"sample.txt";file.write_text("old",encoding="utf-8");written=file.write_text("café\n",encoding="utf-8");read=file.read_text(encoding="utf-8")
        try:file.read_text(newline=None)
        except TypeError as error:newline={"accepted":False,"error_type":type(error).__name__,"message":str(error)}
        else:newline={"accepted":True}
    result={"python":platform.python_version(),"read_text_signature":str(inspect.signature(Path.read_text)),"write_text_signature":str(inspect.signature(Path.write_text)),"write_utf8_characters":written,"read_back":read,"existing_file_replaced":read=="café\n","json_dumps_type":type(json.dumps({"x":1})).__name__,"read_text_newline":newline,"python313_execution":False}
    out=Path(__file__).parent/"runs/2026-10-22-dataset/python312-facts.json";out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,indent=2)+"\n");print(json.dumps(result,indent=2))

if __name__=="__main__":main()
