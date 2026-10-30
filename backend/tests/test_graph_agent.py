"""The graph-agent experiment: the config must be a valid graph, and the live one-prompt agent unchanged."""

from app import agent_template


def configs(client, company):
    with client.Session() as s:
        return agent_template.agent_config(s, company), agent_template.agent_config(s, company, kind="graph"), \
            agent_template.company_names(s, company.id)


def task(config):
    return config["agent_config"]["tasks"][0]


def test_graph_is_well_formed(client, company):
    _, graph, _ = configs(client, company)
    llm = task(graph)["tools_config"]["llm_agent"]
    assert llm["agent_type"] == "graph_agent"
    nodes = {n["id"]: n for n in llm["llm_config"]["nodes"]}
    assert llm["llm_config"]["current_node_id"] in nodes
    for node in nodes.values():
        for edge in node["edges"]:
            assert edge["to_node_id"] in nodes, (node["id"], edge["to_node_id"])
        if node.get("node_type") == "router":
            assert "prompt" not in node and any(e["condition_type"] == "unconditional" for e in node["edges"])
        if node.get("node_type") == "static":
            assert node["function_call"] == "end_call" and node["edges"] == []
            assert set(node["static_message"]) == {"hi", "en"}
    targets = {e["to_node_id"] for n in nodes.values() for e in n["edges"]}
    assert set(nodes) - targets == {"route"}  # every other node is reachable


def test_graph_tools_are_scoped_to_existing_nodes(client, company):
    _, graph, _ = configs(client, company)
    nodes = {n["id"]: n for n in task(graph)["tools_config"]["llm_agent"]["llm_config"]["nodes"]}
    tools = task(graph)["tools_config"]["api_tools"]
    for name, params in tools["tools_params"].items():
        assert params["scope"] == "node" and set(params["nodes"]) <= set(nodes), name
    called = {n["function_call"] for n in nodes.values() if n.get("function_call") not in (None, "end_call")}
    assert called <= {t["name"] for t in tools["tools"]}
    assert {t["name"] for t in tools["tools"]} == {"check_visit", "get_doctor_brief"}  # no resolve_names


def test_graph_hands_the_end_of_the_call_to_its_end_nodes(client, company):
    simple, graph, _ = configs(client, company)
    assert "call_cancellation_prompt" in task(simple)["task_config"]
    # the graph's hangup check only recognises Saathi's own closing line, never the rep's words
    assert task(graph)["task_config"]["call_cancellation_prompt"] != task(simple)["task_config"]["call_cancellation_prompt"]
    assert "record हो गया" in task(graph)["task_config"]["call_cancellation_prompt"]
    # everything else the comparison holds fixed is identical (the graph waits longer for a pause)
    for key in ("synthesizer", "input", "output"):
        assert task(graph)["tools_config"][key] == task(simple)["tools_config"][key]
    g, s = task(graph)["tools_config"]["transcriber"], task(simple)["tools_config"]["transcriber"]
    assert g["endpointing"] > s["endpointing"] and {**g, "endpointing": 0} == {**s, "endpointing": 0}
    assert task(simple)["tools_config"]["llm_agent"]["agent_type"] == "simple_llm_agent"
    assert "scope" not in task(simple)["tools_config"]["api_tools"]["tools_params"]["resolve_names"]


def test_graph_prompts_name_no_company_records(client, company):
    """Examples are placeholders; the company's doctors, products and chemists come from the call."""
    _, graph, names = configs(client, company)
    llm = task(graph)["tools_config"]["llm_agent"]["llm_config"]
    texts = [llm["agent_information"], llm["routing_instructions"]]
    for n in llm["nodes"]:
        texts += [n.get("prompt", ""), *n.get("static_message", {}).values()]
        texts += [e.get("condition", "") for e in n["edges"]]
    text = "\n".join(texts)
    for name in names["doctors"] + names["products"] + names["chemists"]:
        assert name not in text, name
    assert "[[" not in text


def test_the_check_always_runs_after_the_reps_first_message(client, company):
    """Listening hands over by rule, not by the router's judgement (which once kept the call in listen)."""
    _, graph, _ = configs(client, company)
    nodes = {n["id"]: n for n in task(graph)["tools_config"]["llm_agent"]["llm_config"]["nodes"]}
    (edge,) = nodes["listen"]["edges"]
    assert edge["to_node_id"] == "visit" and edge["condition_type"] == "unconditional"


def test_graph_model_is_one_setting_for_conversation_and_routing(client, company):
    _, graph, _ = configs(client, company)
    llm = task(graph)["tools_config"]["llm_agent"]["llm_config"]
    assert llm["model"] == llm["routing_model"] == agent_template.GRAPH_MODEL
