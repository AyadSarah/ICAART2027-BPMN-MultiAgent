import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from agent import run, check_xml, SYSTEM_PROMPT, response_text
from layout import make_visualization

VALID='<?xml version="1.0" encoding="utf-8"?>\n<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs">\n <process id="P" isExecutable="false">\n  <startEvent id="start"/><task id="task" name="Review"/><endEvent id="end"/>\n  <sequenceFlow id="s1" sourceRef="start" targetRef="task"/>\n  <sequenceFlow id="s2" sourceRef="task" targetRef="end"/>\n </process>\n</definitions>'

class FakeMessages:
    def create(self,**kwargs):
        self.kwargs=kwargs
        return SimpleNamespace(content=[SimpleNamespace(type="text",text=VALID)],
            model=kwargs["model"],id="test-message",stop_reason="end_turn",usage=None)
class FakeClient:
    def __init__(self):self.messages=FakeMessages()

class AgentTests(unittest.TestCase):
    def test_parse(self):
        d=check_xml(VALID)
        self.assertTrue(d["xml_well_formed"])
        self.assertEqual(d["sequence_flow_count"],2)
    def test_invalid_kept(self):
        self.assertFalse(check_xml("<definitions")["xml_well_formed"])
    def test_exact_generate_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); source=root/"example.txt"
            source.write_text("Review a request then end.",encoding="utf-8")
            client=FakeClient()
            dest=run(source,root/"outputs","mock-claude",max_tokens=2048,client=client)
            self.assertEqual((dest/"initial.bpmn").read_text(encoding="utf-8"),VALID)
            data=json.loads((dest/"metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(data["model_requested"],"mock-claude")
            self.assertEqual(data["stop_reason"],"end_turn")
            self.assertEqual(client.messages.kwargs["system"],SYSTEM_PROMPT)
            self.assertEqual(client.messages.kwargs["max_tokens"],2048)
            self.assertTrue((dest/"visualization.bpmn").exists())
    def test_adapter(self):
        rendered,status=make_visualization(VALID)
        self.assertIsNotNone(rendered)
        self.assertTrue(check_xml(rendered)["has_bpmn_diagram"])
    def test_text_chunks(self):
        msg=SimpleNamespace(content=[SimpleNamespace(type="text",text="<xml>"),SimpleNamespace(type="text",text="abc")])
        self.assertEqual(response_text(msg),"<xml>abc")

if __name__=="__main__":unittest.main()
