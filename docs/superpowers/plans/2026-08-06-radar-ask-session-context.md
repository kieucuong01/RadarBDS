# Radar Ask Session Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Radar Ask follow-up questions inherit verified context from the current chat session without remembering other chats or adding an LLM call.

**Architecture:** Add one owner-scoped repository read for bounded recent messages and successful routes, then resolve those records into typed `SessionMemory` plus six sanitized recent turns. Hydrate `AskContext` before orchestration; deterministic routing inherits only missing filters, while the DeepSeek planner receives the same bounded context.

**Tech Stack:** Python 3.12, Flask, PostgreSQL/psycopg 3, Pydantic 2, pytest, DeepSeek typed planner.

## Global Constraints

- Memory is limited to the current `session_id`; a new chat has no inherited context.
- Do not add a provider request, database table, schema migration, crawl, or reprocess.
- Explicit values in the current question override page context; page context overrides session memory.
- Only allowlisted typed route arguments may become structured memory.
- Raw URLs, phone numbers, evidence payloads, and arbitrary tool arguments never enter session memory.
- Keep recent turns at six messages and preserve existing authentication, tier quotas, budget stops, and redaction.

## File Structure

- Create `services/radar_ask/session_context.py`: convert bounded repository records into typed request context.
- Modify `services/radar_ask/contracts.py`: define immutable typed `SessionMemory` carried by `AskContext`.
- Modify `services/radar_ask/repository.py`: add one owner-scoped bounded context read.
- Modify `services/radar_ask/service.py`: hydrate context with the same repository instance used by orchestration.
- Modify `services/radar_ask/planner.py`: send redacted recent turns and structured memory to DeepSeek.
- Modify `services/radar_ask/routing.py`: inherit only missing typed filters in fast paths.
- Test in focused Radar Ask repository, context, service, planner, routing, API, and orchestrator suites.

---

### Task 1: Owner-Scoped Session Context Read

**Files:**
- Modify: `services/radar_ask/repository.py`
- Modify: `tests/test_radar_ask_repository.py`

**Interfaces:**
- Produces: `RadarAskSessionContextRecord(messages: tuple[RadarAskMessageRecord, ...], routes: tuple[dict[str, Any], ...])`.
- Produces: `RadarAskRepository.load_session_context(*, user_id: int, session_id: UUID, message_limit: int = 6, route_limit: int = 4) -> RadarAskSessionContextRecord`.

- [ ] **Step 1: Write the failing ownership and ordering test**

```python
def test_load_session_context_is_owned_bounded_and_latest_first(repository_env):
    repository, users = repository_env
    session = repository.create_session(user_id=users.free_id, title="Định Hòa")
    for index in range(8):
        repository.create_message(
            user_id=users.free_id,
            session_id=session.id,
            role="user" if index % 2 == 0 else "assistant",
            content=f"turn-{index}",
        )

    context = repository.load_session_context(
        user_id=users.free_id,
        session_id=session.id,
        message_limit=6,
        route_limit=4,
    )

    assert [message.content for message in context.messages] == [
        "turn-2", "turn-3", "turn-4", "turn-5", "turn-6", "turn-7"
    ]
    with pytest.raises(OwnedResourceNotFound):
        repository.load_session_context(
            user_id=users.vip_id,
            session_id=session.id,
        )
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
& 'C:\Users\ASUS\Documents\Claude\Projects\Radar BDS\.local\codex-test-venv\Scripts\python.exe' -X utf8 -m pytest -p no:cacheprovider tests\test_radar_ask_repository.py::test_load_session_context_is_owned_bounded_and_latest_first -q
```

Expected: FAIL because `load_session_context` does not exist.

- [ ] **Step 3: Implement the record and bounded read**

Add the record:

```python
@dataclass(frozen=True)
class RadarAskSessionContextRecord:
    messages: tuple[RadarAskMessageRecord, ...]
    routes: tuple[dict[str, Any], ...]
```

Implement one transaction that:

```python
def load_session_context(self, *, user_id, session_id, message_limit=6, route_limit=4):
    bounded_messages = max(1, min(int(message_limit), 6))
    bounded_routes = max(1, min(int(route_limit), 4))
    with get_conn() as conn:
        owned = conn.execute(
            "SELECT 1 FROM radar_ask_sessions WHERE id=? AND user_id=?",
            (session_id, user_id),
        ).fetchone()
        if owned is None:
            raise OwnedResourceNotFound("session was not found")
        # Select the latest bounded messages, return them chronological.
        # Select completed/insufficient non-null route_json newest-first.
    return RadarAskSessionContextRecord(messages=messages, routes=routes)
```

The route query must include both `session_id=?` and `user_id=?`, accept only
`status IN ('completed','insufficient')`, and return only `route_json`.

- [ ] **Step 4: Run focused repository tests**

Run the test from Step 2 plus:

```powershell
& 'C:\Users\ASUS\Documents\Claude\Projects\Radar BDS\.local\codex-test-venv\Scripts\python.exe' -X utf8 -m pytest -p no:cacheprovider tests\test_radar_ask_repository.py::test_messages_feedback_and_reads_require_session_ownership -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add -- services/radar_ask/repository.py tests/test_radar_ask_repository.py
git commit -m "Add bounded Radar Ask session context read"
```

---

### Task 2: Typed Session Memory Resolver

**Files:**
- Create: `services/radar_ask/session_context.py`
- Modify: `services/radar_ask/contracts.py`
- Create: `tests/test_radar_ask_session_context.py`

**Interfaces:**
- Consumes: `RadarAskSessionContextRecord` from Task 1.
- Produces: `SessionMemory` with `city`, `wards`, `road`, `property_types`, `budget_ty`, `min_area_m2`, `max_area_m2`, `listing_id`, and `previous_question_type`.
- Produces: `hydrate_session_context(base: AskContext, stored: RadarAskSessionContextRecord) -> AskContext`.

- [ ] **Step 1: Write failing resolver tests**

```python
def test_resolver_keeps_latest_allowlisted_route_values_and_six_turns():
    stored = context_record(
        messages=[message("user", f"turn-{index}") for index in range(8)],
        routes=[
            route("deal_search", {"wards": ["Tân An"], "max_budget_ty": 3}),
            route("deal_search", {"wards": ["Định Hòa"], "sql": "SELECT *"}),
        ],
    )

    hydrated = hydrate_session_context(
        AskContext(user_id=7, tier="admin"),
        stored,
    )

    assert hydrated.session_memory.wards == ["Tân An"]
    assert hydrated.session_memory.budget_ty == 3
    assert hydrated.session_memory.previous_question_type == "deal_search"
    assert len(hydrated.recent_turns) == 6
    assert "SELECT" not in hydrated.model_dump_json()


def test_resolver_never_crosses_context_instances():
    empty = hydrate_session_context(
        AskContext(user_id=8, tier="admin"),
        context_record(messages=[], routes=[]),
    )
    assert empty.session_memory.wards == []
    assert empty.recent_turns == []
```

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
& 'C:\Users\ASUS\Documents\Claude\Projects\Radar BDS\.local\codex-test-venv\Scripts\python.exe' -X utf8 -m pytest -p no:cacheprovider tests\test_radar_ask_session_context.py -q
```

Expected: collection failure because the resolver and model do not exist.

- [ ] **Step 3: Add typed contracts and resolver**

Add to `contracts.py`:

```python
class SessionMemory(ContractModel):
    city: str | None = Field(default=None, max_length=120)
    wards: list[str] = Field(default_factory=list, max_length=10)
    road: str | None = Field(default=None, max_length=180)
    property_types: list[str] = Field(default_factory=list, max_length=5)
    budget_ty: float | None = Field(default=None, gt=0, le=500)
    min_area_m2: float | None = Field(default=None, gt=0, le=100_000)
    max_area_m2: float | None = Field(default=None, gt=0, le=100_000)
    listing_id: int | None = Field(default=None, gt=0)
    previous_question_type: str | None = Field(default=None, max_length=80)


class AskContext(ContractModel):
    # existing fields stay unchanged
    session_memory: SessionMemory = Field(default_factory=SessionMemory)
```

Implement `session_context.py` with an exact allowlist mapping for:

```python
ALLOWED_ARGUMENT_FIELDS = {
    "city", "ward", "wards", "areas", "road", "property_type",
    "property_types", "budget_ty", "max_budget_ty", "min_area_m2",
    "max_area_m2", "listing_id",
}
```

Process stored routes newest-first and fill each memory field only once. Format
recent messages as `user: ...` or `assistant: ...`, cap each at 600 characters,
and keep the latest six in chronological order.

- [ ] **Step 4: Run resolver and contract tests**

Run:

```powershell
& 'C:\Users\ASUS\Documents\Claude\Projects\Radar BDS\.local\codex-test-venv\Scripts\python.exe' -X utf8 -m pytest -p no:cacheprovider tests\test_radar_ask_session_context.py tests\test_radar_ask_contracts.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add -- services/radar_ask/contracts.py services/radar_ask/session_context.py tests/test_radar_ask_session_context.py
git commit -m "Resolve typed Radar Ask session memory"
```

---

### Task 3: Hydrate Service And Planner Context

**Files:**
- Modify: `services/radar_ask/service.py`
- Modify: `services/radar_ask/planner.py`
- Create: `tests/test_radar_ask_service.py`
- Modify: `tests/test_radar_ask_api.py`
- Modify: `tests/test_radar_ask_planner.py`

**Interfaces:**
- Consumes: `hydrate_session_context(base, stored)` from Task 2.
- Changes: `_dependencies(repository: RadarAskRepository | None = None)` reuses the repository that loaded context.
- Changes: `run_radar_question` loads context only when `request.session_id` is present.

- [ ] **Step 1: Write failing service hydration test**

Patch `run_question` and `_dependencies` so the test observes the final context:

```python
def test_run_radar_question_hydrates_only_the_owned_current_session(monkeypatch):
    request = AskQuestionRequest(question="Giá tầm 3 tỷ thôi", session_id=SESSION_ID)
    repository = FakeContextRepository(
        context=context_record(
            messages=[message("user", "Đất Định Hòa thì sao?")],
            routes=[route("deal_search", {"wards": ["Định Hòa"]})],
        )
    )
    captured = {}
    monkeypatch.setattr(service, "get_repository", lambda: repository)
    monkeypatch.setattr(service, "run_question", lambda request, context, **kwargs: captured.setdefault("context", context) or answered_run())

    service.run_radar_question(
        request,
        AskContext(user_id=7, tier="admin"),
        idempotency_key="follow-up",
    )

    assert captured["context"].session_memory.wards == ["Định Hòa"]
    assert captured["context"].recent_turns == ["user: Đất Định Hòa thì sao?"]
```

- [ ] **Step 2: Write failing planner serialization test**

```python
def test_planner_receives_bounded_redacted_session_context():
    planner(...)(
        request=AskQuestionRequest(question="Rẻ hơn nữa thì sao?"),
        context=AskContext(
            user_id=7,
            tier="admin",
            recent_turns=["user: Tân An khoảng 500 m2"],
            session_memory=SessionMemory(wards=["Tân An"], min_area_m2=450, max_area_m2=550),
        ),
        allowed_tools=tuple(DEFAULT_TOOL_REGISTRY.registrations),
    )
    payload = json.loads(provider.requests[0].messages[-1].content)
    assert payload["conversation_context"]["memory"]["wards"] == ["Tân An"]
    assert payload["conversation_context"]["recent_turns"] == ["user: Tân An khoảng 500 m2"]
```

- [ ] **Step 3: Run both tests and verify RED**

Run the two exact pytest node IDs. Expected: the service context is empty and
the planner payload lacks `conversation_context`.

- [ ] **Step 4: Implement hydration and planner payload**

In `service.py`, create one repository, load only the owned `request.session_id`,
hydrate the base context, and pass the same repository to `_dependencies`.

In `planner.py`, add this redacted payload:

```python
"conversation_context": {
    "memory": _redact(context.session_memory.model_dump(mode="json")),
    "recent_turns": _redact(context.recent_turns),
},
```

Update the system prompt: explicit current-question fields win; inherited fields
fill omissions only; ask one clarification when context conflicts.

- [ ] **Step 5: Run service, planner, API, and redaction tests**

Run:

```powershell
& 'C:\Users\ASUS\Documents\Claude\Projects\Radar BDS\.local\codex-test-venv\Scripts\python.exe' -X utf8 -m pytest -p no:cacheprovider tests\test_radar_ask_service.py tests\test_radar_ask_planner.py tests\test_radar_ask_api.py -q
```

Expected: PASS and sensitive fixtures remain absent from serialized provider
requests.

- [ ] **Step 6: Commit**

```powershell
git add -- services/radar_ask/service.py services/radar_ask/planner.py tests/test_radar_ask_service.py tests/test_radar_ask_planner.py tests/test_radar_ask_api.py
git commit -m "Hydrate Radar Ask current-chat context"
```

---

### Task 4: Typed Fast-Path Inheritance

**Files:**
- Modify: `services/radar_ask/routing.py`
- Modify: `tests/test_radar_ask_routing.py`

**Interfaces:**
- Consumes: `AskContext.session_memory` from Task 2.
- Produces: typed route arguments with precedence current question, page context, session memory.

- [ ] **Step 1: Write failing multi-turn routing tests**

```python
def test_budget_follow_up_inherits_current_session_ward_and_property_type():
    decision = route_question(
        AskQuestionRequest(question="Giá tầm 3 tỷ đổ lại thôi"),
        AskContext(
            user_id=7,
            tier="admin",
            session_memory=SessionMemory(
                wards=["Định Hòa"], property_types=["dat_nen"]
            ),
        ),
        planner=forbidden_planner,
    )
    assert decision.question_type == "budget_match"
    assert decision.tool_calls[0].arguments == {
        "budget_ty": 3.0,
        "wards": ["Định Hòa"],
        "property_types": ["dat_nen"],
        "limit": 10,
    }


def test_explicit_new_ward_overrides_session_ward():
    decision = route_question(
        AskQuestionRequest(question="Đất Tân An giờ giá sao?"),
        AskContext(
            user_id=7,
            tier="admin",
            session_memory=SessionMemory(wards=["Định Hòa"]),
        ),
    )
    assert decision.tool_calls[0].arguments["areas"] == ["Tân An"]
```

- [ ] **Step 2: Run and verify RED**

Run the two exact tests. Expected: budget follow-up invokes the planner or drops
the ward; explicit override test documents current precedence.

- [ ] **Step 3: Implement minimal inheritance helpers**

Add helpers that resolve explicit values first:

```python
def _effective_wards(explicit_wards, context):
    if explicit_wards:
        return explicit_wards
    if context.page.ward:
        return [context.page.ward]
    return list(context.session_memory.wards)


def _effective_property_types(explicit_property_type, context):
    if explicit_property_type:
        return [explicit_property_type]
    return list(context.session_memory.property_types)
```

Use them only for missing arguments in area price, budget match, market trend,
price-drop ranking, and planner-bound follow-up paths. Do not inherit a ward when
the current question explicitly asks for `phường khác`, `khu khác`, or `chỗ khác`;
that must fall through to the planner with recent turns.

- [ ] **Step 4: Run full routing tests**

Run:

```powershell
& 'C:\Users\ASUS\Documents\Claude\Projects\Radar BDS\.local\codex-test-venv\Scripts\python.exe' -X utf8 -m pytest -p no:cacheprovider tests\test_radar_ask_routing.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add -- services/radar_ask/routing.py tests/test_radar_ask_routing.py
git commit -m "Inherit typed filters in Radar Ask follow-ups"
```

---

### Task 5: Integrated Verification And Production Release

**Files:**
- Modify only if a focused integration regression requires it.

**Interfaces:**
- Verifies all outputs from Tasks 1-4 as one current-session flow.

- [ ] **Step 1: Add one service-level conversation regression**

Use a fake owned repository and fake planner to assert this sequence:

```text
Đất Định Hòa thì sao?
Giá tầm 3 tỷ đổ lại thôi
```

The second request must send `wards=["Định Hòa"]`, `budget_ty=3`, preserve the
current `session_id`, and never load another user's session.

- [ ] **Step 2: Run the 80/20 Radar Ask suite**

```powershell
& 'C:\Users\ASUS\Documents\Claude\Projects\Radar BDS\.local\codex-test-venv\Scripts\python.exe' -X utf8 -m pytest -p no:cacheprovider tests\test_radar_ask_repository.py tests\test_radar_ask_session_context.py tests\test_radar_ask_service.py tests\test_radar_ask_planner.py tests\test_radar_ask_routing.py tests\test_radar_ask_orchestrator.py tests\test_radar_ask_api.py tests\test_radar_ask_answer_presenters.py tests\test_radar_ask_validation.py tests\test_radar_ask_market_tools.py -q
```

Expected: zero failures.

- [ ] **Step 3: Run syntax and diff gates**

```powershell
& 'C:\Users\ASUS\Documents\Claude\Projects\Radar BDS\.local\codex-test-venv\Scripts\python.exe' -X utf8 -m py_compile services\radar_ask\contracts.py services\radar_ask\repository.py services\radar_ask\session_context.py services\radar_ask\service.py services\radar_ask\planner.py services\radar_ask\routing.py
git diff --check
git status --short --branch
```

Expected: clean checks and only scoped commits ahead of `origin/main`.

- [ ] **Step 4: Push and deploy**

```powershell
git push origin HEAD:main
.\scripts\deploy_production.ps1
```

- [ ] **Step 5: Production smoke**

Verify deployed SHA, `radar-bds.service`, `radar-ask-worker.service`, dashboard
HTTP 200, then use one authenticated admin session to ask the two-turn sequence.
Confirm the second stored route contains Định Hòa plus the 3-billion budget and
the grounded answer has at least one relevant source card.
