"""Optional deterministic BPMN-DI visualization adapter (never alters raw LLM output).

This is a convenience renderer, not BPMN validation or semantic repair.
"""
from collections import defaultdict, deque
import xml.etree.ElementTree as ET

BPMN='http://www.omg.org/spec/BPMN/20100524/MODEL'
BPMNDI='http://www.omg.org/spec/BPMN/20100524/DI'
DC='http://www.omg.org/spec/DD/20100524/DC'
DI='http://www.omg.org/spec/DD/20100524/DI'
for prefix,uri in [('bpmn',BPMN),('bpmndi',BPMNDI),('dc',DC),('di',DI)]: ET.register_namespace(prefix,uri)
def tag(ns,name): return f'{{{ns}}}{name}'
NODE_TYPES={'startEvent','endEvent','intermediateCatchEvent','intermediateThrowEvent','task','userTask','serviceTask','manualTask','businessRuleTask','scriptTask','sendTask','receiveTask','subProcess','callActivity','exclusiveGateway','inclusiveGateway','parallelGateway','eventBasedGateway','complexGateway','boundaryEvent'}
def local(el): return el.tag.rsplit('}',1)[-1]

def make_visualization(xml_text):
    """Return (XML visualization, status); preserve process element structure unchanged."""
    try: root=ET.fromstring(xml_text)
    except ET.ParseError as e: return None,f'Invalid XML: {e}'
    if root.tag!=tag(BPMN,'definitions'): return None,'Root is not BPMN definitions'
    if root.find(tag(BPMNDI,'BPMNDiagram')) is not None: return xml_text,'BPMN-DI already present; no adapter needed'
    process=root.find(tag(BPMN,'process'))
    if process is None or not process.get('id'): return None,'No process with id'
    nodes=[e for e in process.iter() if local(e) in NODE_TYPES and e.get('id')]
    flows=[e for e in process.iter() if local(e)=='sequenceFlow' and e.get('id')]
    if not nodes: return None,'No flow nodes'
    node_by_id={e.get('id'):e for e in nodes}
    if any(f.get('sourceRef') not in node_by_id or f.get('targetRef') not in node_by_id for f in flows): return None,'Dangling sequenceFlow references; cannot draw'
    lanes=[e for e in process.iter() if local(e)=='lane' and e.get('id')]
    lane_for={}
    for idx,lane in enumerate(lanes):
        for ref in lane.findall(tag(BPMN,'flowNodeRef')):
            if ref.text: lane_for[ref.text.strip()]=idx
    adjacent=defaultdict(list)
    indegree={n:0 for n in node_by_id}
    for f in flows:
        source,target=f.get('sourceRef'),f.get('targetRef')
        adjacent[source].append(target)
        indegree[target]+=1
    roots=[n for n in node_by_id if indegree[n]==0]
    if not roots: roots=[next(iter(node_by_id))]
    level={n:0 for n in roots}; queue=deque(roots)
    while queue:
        u=queue.popleft()
        for v in adjacent[u]:
            if v not in level:
                level[v]=level[u]+1; queue.append(v)
    for n in node_by_id: level.setdefault(n,max(level.values(),default=0)+1)
    grouped=defaultdict(list)
    for n in node_by_id: grouped[level[n]].append(n)
    pos={}
    lane_height=165
    for depth,node_ids in sorted(grouped.items()):
        per_lane=defaultdict(int)
        for nid in node_ids:
            row=lane_for.get(nid,0)
            offset=per_lane[row]; per_lane[row]+=1
            e=node_by_id[nid]; kind=local(e)
            w,h=(36,36) if kind.endswith('Event') else (50,50) if 'Gateway' in kind else (120,80)
            x=160+depth*205+offset*140
            y=75+row*lane_height+(lane_height-h)/2
            pos[nid]=(x,y,w,h)
    max_x=max(x+w for x,y,w,h in pos.values())+90
    diagram=ET.SubElement(root,tag(BPMNDI,'BPMNDiagram'),{'id':'Auto_Diagram'})
    plane=ET.SubElement(diagram,tag(BPMNDI,'BPMNPlane'),{'id':'Auto_Plane','bpmnElement':process.get('id')})
    for i,lane in enumerate(lanes):
        sh=ET.SubElement(plane,tag(BPMNDI,'BPMNShape'),{'id':f'Auto_Shape_{lane.get("id")}','bpmnElement':lane.get('id'),'isHorizontal':'true'})
        ET.SubElement(sh,tag(DC,'Bounds'),{'x':'95','y':str(60+i*lane_height),'width':str(max_x-70),'height':str(lane_height)})
    for nid,(x,y,w,h) in pos.items():
        sh=ET.SubElement(plane,tag(BPMNDI,'BPMNShape'),{'id':f'Auto_Shape_{nid}','bpmnElement':nid})
        ET.SubElement(sh,tag(DC,'Bounds'),{'x':str(round(x,1)),'y':str(round(y,1)),'width':str(w),'height':str(h)})
    for f in flows:
        src=f.get('sourceRef'); dst=f.get('targetRef')
        x1,y1,w1,h1=pos[src]; x2,y2,w2,h2=pos[dst]
        begin=(x1+w1,y1+h1/2); end=(x2,y2+h2/2)
        edge=ET.SubElement(plane,tag(BPMNDI,'BPMNEdge'),{'id':f'Auto_Edge_{f.get("id")}','bpmnElement':f.get('id')})
        waypoints=[begin,end] if abs(begin[1]-end[1])<1 else [begin,((begin[0]+end[0])/2,begin[1]),((begin[0]+end[0])/2,end[1]),end]
        for x,y in waypoints: ET.SubElement(edge,tag(DI,'waypoint'),{'x':str(round(x,1)),'y':str(round(y,1))})
    root.set('exporter','Research visualization adapter (not raw LLM output)')
    return ET.tostring(root,encoding='unicode',xml_declaration=True),'Added diagram coordinates; process structure unchanged'
