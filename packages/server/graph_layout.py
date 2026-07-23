from collections import deque
from typing import Any, Dict, List
from schemas import ReactFlowEdge, ReactFlowNode, NodePosition, NodeData


def compute_graph_layout(events: List[Any]) -> Dict[str, Any]:
    """Process a list of session events to construct a React Flow compatible DAG.

    Computes node coordinates using a deterministic hierarchical layering algorithm.
    """
    if not events:
        return {"nodes": [], "edges": []}

    # 1. Group events by their run_id (event_id)
    node_data_map: Dict[str, Dict[str, Any]] = {}
    for ev in events:
        eid = ev.event_id
        if eid not in node_data_map:
            # Format agent type for React Flow custom nodes
            # options: ChainNode, LLMNode, ToolNode, RetrieverNode
            agent_type = ev.agent_type.lower()
            if agent_type == "llm":
                node_type = "LLMNode"
            elif agent_type == "tool":
                node_type = "ToolNode"
            elif agent_type == "retriever":
                node_type = "RetrieverNode"
            else:
                node_type = "ChainNode"

            node_data_map[eid] = {
                "id": eid,
                "type": node_type,
                "parent_id": ev.parent_event_id,
                "agent_name": ev.agent_name,
                "event_type": ev.event_type,
                "started_at": ev.timestamp,
                "ended_at": None,
                "status": ev.status,
                "latency_ms": ev.latency_ms,
                "token_count": None,
            }

        # Merge end/error states
        node = node_data_map[eid]
        # Timestamps
        if ev.timestamp < node["started_at"]:
            node["started_at"] = ev.timestamp
        if ev.timestamp > node["started_at"]:
            node["ended_at"] = ev.timestamp

        # Status: error takes precedence
        if ev.status == "error":
            node["status"] = "error"
        elif ev.status == "completed" and node["status"] != "error":
            node["status"] = "completed"

        # Latency
        if ev.latency_ms is not None:
            node["latency_ms"] = ev.latency_ms
        elif node["ended_at"]:
            dur = (node["ended_at"] - node["started_at"]).total_seconds() * 1000
            node["latency_ms"] = int(dur)

        # Tokens
        if ev.payload and isinstance(ev.payload, dict):
            # Try to grab token counts
            tokens = ev.payload.get("total_tokens") or ev.payload.get(
                "total_token_count"
            )
            if tokens is not None:
                node["token_count"] = tokens

    # 2. Build graph adjacency list
    nodes_list = list(node_data_map.values())
    node_ids = set(node_data_map.keys())

    adj: Dict[str, List[str]] = {nid: [] for nid in node_ids}
    in_degree: Dict[str, int] = {nid: 0 for nid in node_ids}

    for node in nodes_list:
        pid = node["parent_id"]
        # Only add edge if parent actually exists in this run context
        if pid and pid in node_ids:
            adj[pid].append(node["id"])
            in_degree[node["id"]] += 1

    # 3. Layer nodes using BFS (hierarchical ranking)
    # Find roots
    roots = [nid for nid in node_ids if in_degree[nid] == 0]
    layer_map: Dict[str, int] = {}

    # Initialize roots at layer 0
    queue = deque()
    for root in roots:
        layer_map[root] = 0
        queue.append(root)

    while queue:
        curr = queue.popleft()
        curr_layer = layer_map[curr]
        for child in adj[curr]:
            # Layer is maximum distance from roots (ensures child is always below all parents)
            new_layer = curr_layer + 1
            if child not in layer_map or new_layer > layer_map[child]:
                layer_map[child] = new_layer
                queue.append(child)

    # Clean up any nodes missed (shouldn't happen in a DAG, but safe fallback)
    for nid in node_ids:
        if nid not in layer_map:
            layer_map[nid] = 0

    # 4. Group and sort nodes by layer
    layers: Dict[int, List[Dict[str, Any]]] = {}
    for node in nodes_list:
        layer_idx = layer_map[node["id"]]
        if layer_idx not in layers:
            layers[layer_idx] = []
        layers[layer_idx].append(node)

    # Sort nodes chronologically in each layer
    for layer_idx in layers:
        layers[layer_idx].sort(key=lambda n: n["started_at"])

    # 5. Position nodes in a centered layout
    spacing_x = 280
    spacing_y = 180
    nodes_output: List[ReactFlowNode] = []

    for layer_idx, layer_nodes in layers.items():
        k = len(layer_nodes)
        y_pos = layer_idx * spacing_y

        for i, node in enumerate(layer_nodes):
            # Centered x-position
            x_pos = (i - (k - 1) / 2.0) * spacing_x

            # Label resolves to agent name or fallback to node type
            label = node["agent_name"] or node["type"].replace("Node", "")

            nodes_output.append(
                ReactFlowNode(
                    id=node["id"],
                    type=node["type"],
                    position=NodePosition(x=x_pos, y=y_pos),
                    data=NodeData(
                        label=label,
                        agentName=node["agent_name"],
                        eventType=node["event_type"],
                        durationMs=node["latency_ms"],
                        tokenCount=node["token_count"],
                        status=node["status"],
                    ),
                )
            )

    # 6. Generate edges
    edges_output: List[ReactFlowEdge] = []
    for node in nodes_list:
        pid = node["parent_id"]
        if pid and pid in node_ids:
            edge_type = "error" if node["status"] == "error" else "default"
            edges_output.append(
                ReactFlowEdge(
                    id=f"e-{pid}-{node['id']}",
                    source=pid,
                    target=node["id"],
                    type=edge_type,
                )
            )

    return {
        "nodes": [n.model_dump() for n in nodes_output],
        "edges": [e.model_dump() for e in edges_output],
    }
