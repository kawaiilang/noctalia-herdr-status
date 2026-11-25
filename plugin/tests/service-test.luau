local function validSnapshot(state, overrides)
    local snap = {
        state = state,
        running = state ~= "offline" and state ~= "unknown",
        counts = {
            blocked = state == "blocked" and 1 or 0,
            working = state == "working" and 1 or 0,
            done = 0,
            idle = 0,
            unknown = 0,
            agents = (state == "blocked" or state == "working") and 1 or 0,
            shells = state == "shells" and 1 or 0,
            total = (state == "offline" or state == "empty" or state == "unknown") and 0 or 1,
        },
        agents = {},
        shells = {},
    }
    if overrides then
        for k, v in pairs(overrides) do
            snap[k] = v
        end
    end
    return snap
end

assert(interval == 3000)
assert(#calls == 1 and calls[1].timeout == 2500)
assert(calls[1].argv[2] == "status")
assert(values.status.state == "unknown")

update()
noctalia.state.set("refresh", 1)
assert(#calls == 1, "overlapping polls must be prevented")

local function reply(result)
    calls[#calls].callback(result or { exitCode = 0, stdout = "fixture" })
end

decoded = validSnapshot("blocked", {
    agents = {
        {
            pane_id = "p3",
            name = "review",
            agent = "codex",
            status = "blocked",
            dir = "nixos",
            workspace = "main",
            tab = "1",
            focused = false,
        },
    },
})
reply()
assert(values.status.state == "blocked")
assert(#values.status.agents == 1 and values.status.agents[1].pane_id == "p3")

noctalia.state.set("refresh", 2)
assert(#calls == 2, "refresh request must trigger immediate poll")
decoded = validSnapshot("unknown", {
    running = true,
    counts = { blocked = 0, working = 0, done = 0, idle = 0, unknown = 1, agents = 1, shells = 0, total = 1 },
    agents = { { pane_id = "p3", name = "review", agent = "codex", status = "unknown", dir = "", workspace = "", tab = "", focused = false } },
})
reply()
assert(values.status.running and values.status.agents[1].status == "unknown")
update()
reply({ exitCode = 124, timedOut = true })
assert(values.status.state == "unknown", "timeout must clear stale state")

update()
decodeFails = true
reply()
assert(values.status.state == "unknown")
decodeFails = false

for _, invalid in {
    {},
    { state = "invented" },
    validSnapshot("working", { agents = { { pane_id = "", name = "bad", agent = "", status = "working", dir = "", workspace = "", tab = "", focused = false } } }),
    validSnapshot("working", { agents = { { pane_id = "p1", name = "bad", agent = "", status = "bogus", dir = "", workspace = "", tab = "", focused = false } } }),
    validSnapshot("working", { agents = { { pane_id = "p1", name = "bad", agent = "", status = "working", dir = "", workspace = "", tab = "", focused = "yes" } } }),
} do
    update()
    decoded = invalid
    reply()
    assert(values.status.state == "unknown", "invalid payloads must be rejected")
end

-- Action dispatch: focus with duplicate seq suppression and unknown kind rejection
noctalia.state.set("action", { seq = 1, kind = "focus", pane_id = "p3" })
assert(calls[#calls].argv[2] == "focus" and calls[#calls].argv[3] == "p3")
local countAfterFocus = #calls
noctalia.state.set("action", { seq = 1, kind = "focus", pane_id = "p3" })
assert(#calls == countAfterFocus, "duplicate action seq must be ignored")
reply()
assert(values.actionResult.seq == 1 and values.actionResult.ok)
assert(#calls == countAfterFocus + 1 and calls[#calls].argv[2] == "status", "action completion must trigger refresh")
decoded = validSnapshot("offline")
reply()
assert(values.status.state == "offline")

local beforeUnsupported = #calls
noctalia.state.set("action", { seq = 2, kind = "open" })
assert(#calls == beforeUnsupported, "unsupported actions must be ignored")

-- Even if a poll was already in flight, a failed click needs a fresh list.
update()
local oldPoll = calls[#calls]
noctalia.state.set("action", { seq = 3, kind = "focus", pane_id = "gone" })
reply({ exitCode = 1 })
assert(values.actionResult.seq == 3 and values.actionResult.ok == false)
oldPoll.callback({ exitCode = 0, stdout = "fixture" })
assert(calls[#calls] ~= oldPoll and calls[#calls].argv[2] == "status")
reply()

-- Launch failure must not stall future polls
launched = false
noctalia.state.set("action", { seq = 4, kind = "focus", pane_id = "gone" })
assert(values.actionResult.seq == 4 and values.actionResult.ok == false)
assert(values.status.state == "unknown")
launched = true
local beforeTeardown = #calls
update()
assert(#calls == beforeTeardown + 1)

onExit(0, "reload")
decoded = validSnapshot("working")
reply()
assert(values.status.state == "unknown", "late replies after teardown must be ignored")
update()
assert(#calls == beforeTeardown + 1)
print("Herdr status service fixtures passed")
