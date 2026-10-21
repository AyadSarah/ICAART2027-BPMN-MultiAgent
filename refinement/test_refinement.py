import tempfile
import csv
from pathlib import Path
from refinement_runner import extract_xml,validate,feedback_for,create_messages,load_feedback

XML='''<?xml version="1.0"?><definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs1"><process id="Proc1"><startEvent id="Start1"/><task id="Task1" name="Approve request"/><endEvent id="End1"/><sequenceFlow id="Flow1" sourceRef="Start1" targetRef="Task1"/><sequenceFlow id="Flow2" sourceRef="Task1" targetRef="End1"/></process></definitions>'''
assert extract_xml(XML)[0]==XML
assert extract_xml('```xml\n'+XML+'\n```')[0]==XML
assert extract_xml('not xml')[0] is None
assert validate(XML)['usable']
assert not validate(XML.replace('targetRef="End1"','targetRef="missing"'))['usable']
r={'openai_identified_issues':'misses A','openai_suggested_corrections':'add A',
   'claude_identified_issues':'misses B','claude_suggested_corrections':'add B'}
assert feedback_for(r,'openai','same')[0]=='openai'
assert feedback_for(r,'openai','cross')[0]=='claude'
assert len(create_messages('Test',XML,'self'))==3
assert len(create_messages('Test',XML,'same','misses A','add A'))==1
print('PASS: XML, cross/same feedback selection, self reconstruction')
with tempfile.TemporaryDirectory() as d:
    base=Path(d); ds=base/'dataset'
    (ds/'descriptions').mkdir(parents=True)
    (ds/'selected_for_analysis'/'openai'/'pmo_01').mkdir(parents=True)
    (ds/'descriptions'/'01.txt').write_text('Approve request.',encoding='utf-8')
    (ds/'selected_for_analysis'/'openai'/'pmo_01'/'initial.bpmn').write_text(XML,encoding='utf-8')
    fb=base/'feedback.csv'
    with fb.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['pmo_id','generator',*r.keys()]);w.writeheader();w.writerow({'pmo_id':'01','generator':'openai',**r})
    import subprocess,sys
    runner=str(Path(__file__).parent/'refinement_runner.py')
    res=subprocess.run([sys.executable,runner,'--dataset',str(ds),'--feedback',str(fb),
        '--output',str(base/'out'),'--ids','01','--generators','openai','--dry-run'],capture_output=True,text=True)
    assert res.returncode==0,res.stderr
    records=list(csv.DictReader((base/'out'/'refinement_manifest.csv').open(encoding='utf-8-sig')))
    assert len(records)==3 and set(x['status'] for x in records)=={'READY'}
    assert not (base/'out'/'pmo_01').exists(), 'dry-run must not create case files'
    print('PASS: three dry-run cases, no API calls or refined files')
