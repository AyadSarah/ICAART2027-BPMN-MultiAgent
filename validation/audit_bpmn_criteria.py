"""Structural and feature-presence audit; DOES NOT certify semantic correctness.
Usage: python audit_bpmn_criteria.py model1.bpmn model2.bpmn ...
"""
from collections import Counter
from pathlib import Path
import csv, sys
from lxml import etree
B='http://www.omg.org/spec/BPMN/20100524/MODEL'
D='http://www.omg.org/spec/BPMN/20100524/DI'
N={'b':B,'di':D}
TASKS={'task','userTask','serviceTask','manualTask','businessRuleTask','subProcess','sendTask','receiveTask','scriptTask','callActivity'}
def audit(path):
  d={'model':str(path)}
  try: root=etree.parse(str(path)).getroot()
  except Exception as exc: return {'model':str(path),'parse_error':str(exc)}
  e=[x for x in root.iter() if isinstance(x.tag,str)]; names=Counter(x.tag.split('}')[-1] for x in e)
  ids=[x.get('id') for x in e if x.get('id')]
  flows=[x for x in e if x.tag==f'{{{B}}}sequenceFlow']
  mf=[x for x in e if x.tag==f'{{{B}}}messageFlow']
  edgepairs={(x.get('sourceRef'),x.get('targetRef')) for x in flows}
  reverse_pairs=sum(1 for a,b in edgepairs if (b,a) in edgepairs and a<b)
  labels=[(x.get('name') or '').lower() for x in e if x.tag.split('}')[-1] in TASKS]
  def term(t):return int(any(t in label for label in labels))
  d.update({'xml_well_formed':1,'duplicate_id_count':len(ids)-len(set(ids)),
    'pools_participants':names['participant'],'lanes':names['lane'],
    'message_flows':names['messageFlow'],'sequence_flows':names['sequenceFlow'],
    'data_objects':names['dataObject']+names['dataObjectReference'],'data_stores':names['dataStore']+names['dataStoreReference'],
    'data_associations':names['dataInputAssociation']+names['dataOutputAssociation'],
    'tasks':sum(names[x] for x in TASKS), 'gateways':sum(v for k,v in names.items() if k.endswith('Gateway')),
    'two_way_endpoint_pairs':reverse_pairs,
    'self_loops':sum(1 for x in flows if x.get('sourceRef')==x.get('targetRef')),
    'bpmn_shapes':names['BPMNShape'],'bpmn_edges':names['BPMNEdge'],
    'mentions_cost':term('cost'), 'mentions_quality':term('quality'),
    'mentions_delivery':term('delivery'),
    'mentions_evaluation':term('evaluat'),
    'task_labels': ' | '.join(x.get('name','') for x in e if x.tag.split('}')[-1] in TASKS)})
  d['note']='Feature counts only. Control-flow soundness, graphical overlap, and semantic adequacy need additional review.'
  return d
if __name__=='__main__':
  rows=[audit(Path(x)) for x in sys.argv[1:]]
  if not rows: sys.exit('Pass paths to BPMN XML files')
  fields=list(dict.fromkeys(k for row in rows for k in row))
  w=csv.DictWriter(sys.stdout,fieldnames=fields);w.writeheader();w.writerows(rows)
