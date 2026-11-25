assert(displayed.text == "bar_unknown", "initial load before service must show unknown")

noctalia.state.set("status", {
    state = "blocked",
    running = true,
    counts = { blocked = 2, working = 1, done = 0, idle = 0, unknown = 0, agents = 3, shells = 1, total = 4 },
    agents = {},
    shells = {},
})
assert(displayed.text == "bar_blocked:2")
assert(displayed.glyph == "alert-triangle")
assert(displayed.color == "error" and displayed.glyphColor == "error")
assert(displayed.tooltip[1][2] == "detail_blocked")
assert(displayed.tooltip[2][2] == "count_blocked:2 · count_working:1")
assert(displayed.tooltip[3][2] == "1")

noctalia.state.set("status", {
    state = "working",
    running = true,
    counts = { blocked = 0, working = 3, done = 0, idle = 0, unknown = 0, agents = 3, shells = 0, total = 3 },
    agents = {},
    shells = {},
})
assert(displayed.text == "bar_working:3")
assert(displayed.color == "primary")

noctalia.state.set("status", {
    state = "offline",
    running = false,
    counts = { blocked = 0, working = 0, done = 0, idle = 0, unknown = 0, agents = 0, shells = 0, total = 0 },
    agents = {},
    shells = {},
})
assert(displayed.text == "bar_offline")
assert(displayed.color == "on_surface_variant")

noctalia.state.set("status", { state = "unknown", running = true, counts = { unknown = 2 } })
assert(displayed.text == "bar_agents_unknown:2")
assert(displayed.tooltip[1][2] == "detail_agents_unknown")
assert(displayed.tooltip[2][2] == "count_unknown:2")
noctalia.state.set("status", { state = "idle", running = true, counts = { idle = 1, unknown = 2, agents = 3 } })
assert(displayed.text == "bar_idle:1")
assert(displayed.tooltip[2][2] == "count_idle:1 · count_unknown:2")

onClick()
assert(values.refresh == 1, "click must request refresh")
assert(#toggledPanels == 1 and toggledPanels[1] == "kawaiilang/herdr-status:panel", "click must toggle panel")
assert(#calls == 0 and interval == nil, "bar widget must not poll directly")
print("Herdr status widget fixtures passed")
