"""Download/organize the official PMo 1.0.0 benchmark without modifying source text."""
import argparse
import hashlib
import json
import re
import urllib.request
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

URL = 'https://zenodo.org/records/15857589/files/pmo-dataset.zip?download=1'
EXPECTED_MD5 = '414d9fbc5aa04bc70db8bf1673f4c69a'
BPMN_NS = 'http://www.omg.org/spec/BPMN/20100524/MODEL'

def file_id(path):
    """Get PMo ID only from unambiguous numeric name components."""
    s = path.stem
    matches = re.findall(r'(?<!\d)(?:0?[1-9]|[1-4]\d|5[0-5])(?!\d)', s)
    # A filename might include 'bpmn_01', '01.bpmn', etc.
    if len(matches) == 1:
        return int(matches[0])
    return None

def hash_file(path, algo='md5'):
    h=hashlib.new(algo)
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()

def download(path):
    req=urllib.request.Request(URL,headers={'User-Agent':'PMo-Research-Setup/1.0 (academic reproducibility)'})
    with urllib.request.urlopen(req,timeout=90) as r,open(path,'wb') as out:
        while True:
            chunk=r.read(1024*1024)
            if not chunk: break
            out.write(chunk)

def best_candidates(z):
    names=[n for n in z.namelist() if not n.endswith('/') and '__MACOSX' not in n]
    descriptions={}; models={}
    for name in names:
        p=Path(name)
        i=file_id(p)
        if i is None:continue
        lower=name.lower().replace('\\','/')
        if p.suffix.lower() in ('.txt','.md') and 'description' in lower:
            descriptions.setdefault(i,[]).append(name)
        if p.suffix.lower() in ('.bpmn','.xml') and ('bpmn' in lower) and 'original' not in lower and 'basic' not in lower and 'process' not in lower and 'text' not in lower:
            try:
                root=ET.fromstring(z.read(name))
                if root.tag == '{%s}definitions'%BPMN_NS:
                    models.setdefault(i,[]).append(name)
            except ET.ParseError: pass
    return descriptions, models

def choose(paths, kind):
    if len(paths)==1:return paths[0]
    if not paths:return None
    if kind=='description':
        # favor path in exact descriptions dir
        rank=lambda p: (0 if 'descriptions' in Path(p).parts else 1, len(Path(p).parts),len(p))
    else:
        # favor path containing exact bpmn directory name
        rank=lambda p: (0 if 'bpmn' in [q.lower() for q in Path(p).parts[:-1]] else 1,len(Path(p).parts),len(p))
    ordered=sorted(paths,key=rank)
    if rank(ordered[0])==rank(ordered[1]):
        raise ValueError(f'Ambiguous {kind} files: {paths}')
    return ordered[0]

def prepare(zip_path, output, skip_checksum=False):
    if not zipfile.is_zipfile(zip_path):raise ValueError('Not a ZIP file. Download pmo-dataset.zip from Zenodo.')
    actual_md5=hash_file(zip_path)
    if actual_md5!=EXPECTED_MD5 and not skip_checksum:
        raise ValueError(f'MD5 mismatch: {actual_md5}. Expected {EXPECTED_MD5}. Use the official v1.0.0 archive.')
    inputs=output/'descriptions'; refs=output/'references_bpmn'
    manifest=[]; planned=[]
    with zipfile.ZipFile(zip_path) as z:
        desc,models=best_candidates(z)
        for i in range(1,56):
            d=choose(desc.get(i,[]),'description')
            b=choose(models.get(i,[]),'bpmn')
            if not d or not b:
                raise ValueError(f'Missing PMo pair {i:02d}: description={d}, BPMN={b}. Archive layout may have changed. No partial dataset written.')
            desc_data=z.read(d)
            bpmn_data=z.read(b)
            # UTF-8 and BPMN XML checks, no rewriting the source
            desc_data.decode('utf-8-sig')
            root=ET.fromstring(bpmn_data)
            if root.tag != '{%s}definitions'%BPMN_NS:raise ValueError(f'Invalid BPMN root for {i:02d}')
            planned.append((i,desc_data,bpmn_data))
            manifest.append({'id':f'{i:02d}','description':f'descriptions/{i:02d}.txt', 'reference_bpmn':f'references_bpmn/{i:02d}.bpmn','zip_description':d,'zip_bpmn':b,'description_sha256':hashlib.sha256(desc_data).hexdigest(),'reference_sha256':hashlib.sha256(bpmn_data).hexdigest()})
    inputs.mkdir(parents=True,exist_ok=True);refs.mkdir(parents=True,exist_ok=True)
    for i,d,b in planned:
        (inputs/f'{i:02d}.txt').write_bytes(d)
        (refs/f'{i:02d}.bpmn').write_bytes(b)
    (output/'manifest.json').write_text(json.dumps({'dataset':'PMo 1.0.0','source':URL,'doi':'10.5281/zenodo.15857589','archive_md5':actual_md5,'count':55,'records':manifest},indent=2),encoding='utf-8')
    print(f'Success: 55 descriptions and 55 BPMN references in {output.resolve()}')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--zip',type=Path,help='Path to manually downloaded official pmo-dataset.zip; skips network download')
    p.add_argument('--out',type=Path,default=Path('PMo_ready'))
    p.add_argument('--skip-checksum',action='store_true',help='Only for manually investigating another archive release; not recommended for experiments')
    args=p.parse_args()
    archive=args.zip or Path('pmo-dataset.zip')
    if not archive.exists():
        if args.zip: p.error('The --zip path does not exist')
        print('Downloading official PMo v1.0.0 archive from Zenodo...')
        try:download(archive)
        except Exception as e:raise SystemExit('Download failed. Visit https://zenodo.org/records/15857589 and download pmo-dataset.zip manually; place it next to this script. Details: '+str(e))
    prepare(archive,args.out,args.skip_checksum)
if __name__=='__main__': main()
