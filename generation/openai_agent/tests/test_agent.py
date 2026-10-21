import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from agent import check_xml, run

VALID = '''<?xml version="1.0" encoding="utf-8"?>
<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs">
 <process id="P" isExecutable="false">
  <startEvent id="start"/><task id="task" name="Review"/><endEvent id="end"/>
  <sequenceFlow id="s1" sourceRef="start" targetRef="task"/>
  <sequenceFlow id="s2" sourceRef="task" targetRef="end"/>
 </process>
</definitions>'''

class FakeResponses:
    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(output_text=VALID, model=kwargs["model"], id="test-id", usage=None)

class FakeClient:
    def __init__(self): self.responses = FakeResponses()

class AgentTests(unittest.TestCase):
    def test_valid_diagnostics(self):
        result = check_xml(VALID)
        self.assertTrue(result["xml_well_formed"])
        self.assertTrue(result["bpmn_namespace_root"])
        self.assertEqual(result["sequence_flow_count"], 2)
        self.assertEqual(result["dangling_flow_references"], [])

    def test_invalid_xml_is_preserved(self):
        result = check_xml("<definitions")
        self.assertFalse(result["xml_well_formed"])

    def test_run_writes_files_without_api(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            source = folder / "example.txt"
            source.write_text("Review a request then end.", encoding="utf-8")
            fake = FakeClient()
            target = run(source, folder / "outputs", "mock-model", client=fake)
            self.assertEqual((target / "initial.bpmn").read_text(encoding="utf-8"), VALID)
            self.assertEqual(json.loads((target / "metadata.json").read_text(encoding="utf-8"))["model_requested"], "mock-model")

if __name__ == "__main__": unittest.main()
