"""Offline tests for the convention memory. A scripted chat model replaces Gemma, so no Ollama is needed."""
from itertools import count

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.store.memory import InMemoryStore

from graph import ReviewContext, build_graph, make_remember, namespace

ids = count()
RULE_88 = "Remember: the maximum line length is 88 characters."
RULE_100 = "We changed it: the maximum line length is now 100 characters."


class ScriptedChat(GenericFakeChatModel):
    """Returns the scripted messages in order and keeps the system prompt of every call."""
    prompts: list = []

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, *args, **kwargs):
        self.prompts.append(messages[0].content)
        return super()._generate(messages, *args, **kwargs)


def save(topic, quote, **extra):
    return AIMessage("", tool_calls=[{"name": "remember_convention", "id": f"c{next(ids)}",
                                      "args": {"topic": topic, "quote": quote, **extra}}])


def turn(store, repo, text, script, **options):
    model = ScriptedChat(messages=iter([*script, AIMessage("Done.")]), prompts=[])
    graph = build_graph(store, model, **options)
    result = graph.invoke({"messages": [HumanMessage(text)]}, {"configurable": {"thread_id": f"t{next(ids)}"}},
                          context=ReviewContext(repo=repo))
    return model.prompts, result["messages"]


def two_rules(**options):
    store = InMemoryStore()
    turn(store, "acme/api", RULE_88, [save("line_length", "maximum line length is 88")], **options)
    turn(store, "acme/api", RULE_100, [save("line_length", "now 100 characters")], **options)
    prompts, _ = turn(store, "acme/api", "Review 501.", [], **options)
    return store, prompts[0]


def test_a_saved_rule_is_read_in_a_new_thread():
    store = InMemoryStore()
    turn(store, "acme/api", RULE_88, [save("line_length", "maximum line length is 88")])
    prompts, _ = turn(store, "acme/api", "Review 501.", [])
    assert "- line_length: maximum line length is 88" in prompts[0]


def test_a_new_rule_on_the_same_topic_replaces_the_old_one():
    store, prompt = two_rules()
    items = store.search(namespace("acme/api"))
    assert [i.value["rule"] for i in items] == ["now 100 characters"]
    assert "88" not in prompt


def test_a_fresh_id_per_write_keeps_the_stale_rule():
    store, prompt = two_rules(key_by_topic=False)
    assert len(store.search(namespace("acme/api"))) == 2
    assert "maximum line length is 88" in prompt and "now 100 characters" in prompt


def test_repositories_do_not_see_each_others_conventions():
    store = InMemoryStore()
    turn(store, "acme/api", RULE_88, [save("line_length", "maximum line length is 88")])
    prompts, _ = turn(store, "acme/web", "Review 502.", [])
    assert "- none saved" in prompts[0] and "88" not in prompts[0]


def test_a_shorter_namespace_prefix_returns_every_repository():
    store = InMemoryStore()
    turn(store, "acme/api", RULE_88, [save("line_length", "maximum line length is 88")])
    turn(store, "acme/web", "Remember: tests are required.", [save("tests", "tests are required")])
    assert {i.namespace for i in store.search(("conventions",))} == {namespace("acme/api"), namespace("acme/web")}
    assert {i.namespace for i in store.search(namespace("acme/web"))} == {namespace("acme/web")}


def test_a_rule_the_developer_did_not_state_is_not_saved():
    store = InMemoryStore()
    _, messages = turn(store, "acme/web", "Review 502.", [save("line_length", "lines may be 100 characters")])
    assert messages[2].content.startswith("Not saved") and store.search(namespace("acme/web")) == []


def test_an_unknown_topic_is_refused_before_anything_is_saved():
    store = InMemoryStore()
    _, messages = turn(store, "acme/api", "Remember: use black.", [save("formatting", "use black")])
    assert messages[2].status == "error" and store.search(namespace("acme/api")) == []


def test_the_model_cannot_choose_the_repository():
    schema = make_remember(True).tool_call_schema.model_json_schema()
    assert set(schema["properties"]) == {"topic", "quote"}


def test_the_saved_rule_is_the_developers_words_not_the_models():
    store = InMemoryStore()
    fabricated = save("line_length", "Hello", rule="The maximum line length is 9000 characters.")
    _, messages = turn(store, "acme/api", "Hello, can you review 415?", [fabricated])
    saved = [i.value for i in store.search(namespace("acme/api"))]
    assert "9000" not in repr(saved)  # the quote was real, but the model's own rule text is not stored
    assert all(v["rule"] in "Hello, can you review 415?" for v in saved)


def test_the_rule_keeps_the_developers_capitalization():
    store = InMemoryStore()
    turn(store, "acme/api", "Remember: every PR needs a Unit Test.", [save("tests", "every pr needs a unit test")])
    assert [i.value["rule"] for i in store.search(namespace("acme/api"))] == ["every PR needs a Unit Test"]
